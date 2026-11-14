"""Rewrap one tenant's Amazon tokens under the configured current KEK."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

import psycopg
from cryptography.exceptions import InvalidTag
from psycopg.rows import dict_row

from services.ingest.security.vault import VaultNotConfigured, kek_version, seal, unseal


def rotate_tenant(tenant_id: uuid.UUID, *, apply: bool) -> tuple[int, int]:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set")
    current_version = kek_version()
    verified = 0
    rewrapped = 0
    with psycopg.connect(database_url, row_factory=dict_row) as conn, conn.transaction():
        conn.execute("select set_tenant(%s)", (str(tenant_id),))
        exists = conn.execute("select 1 from tenant where id = %s", (str(tenant_id),)).fetchone()
        if exists is None:
            raise ValueError(f"tenant {tenant_id} does not exist")
        lock = " for update" if apply else ""
        rows = conn.execute(
            f"""select id, key_version, refresh_token_encrypted
                 from amazon_connection
                where tenant_id = %s and refresh_token_encrypted is not null
                order by id{lock}""",
            (str(tenant_id),),
        ).fetchall()
        for row in rows:
            old_version = int(row["key_version"])
            plaintext = unseal(bytes(row["refresh_token_encrypted"]), old_version)
            verified += 1
            if old_version == current_version or not apply:
                continue
            sealed = seal(plaintext)
            conn.execute(
                """update amazon_connection
                      set refresh_token_encrypted = %s, key_version = %s
                    where tenant_id = %s and id = %s and key_version = %s""",
                (sealed.ciphertext, sealed.key_version, str(tenant_id), row["id"], old_version),
            )
            conn.execute(
                """insert into audit_log (tenant_id, action, entity, after)
                   values (%s, 'vault.token_rewrapped', %s, %s::jsonb)""",
                (
                    str(tenant_id),
                    f"amazon_connection:{row['id']}",
                    json.dumps(
                        {
                            "previous_key_version": old_version,
                            "current_key_version": sealed.key_version,
                        }
                    ),
                ),
            )
            rewrapped += 1
    return verified, rewrapped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=uuid.UUID)
    parser.add_argument(
        "--apply", action="store_true", help="persist rewrapped ciphertexts and audit rows"
    )
    args = parser.parse_args()
    try:
        verified, rewrapped = rotate_tenant(args.tenant_id, apply=args.apply)
    except (psycopg.Error, RuntimeError, ValueError, VaultNotConfigured, InvalidTag) as exc:
        print(f"vault rotation failed: {exc}", file=sys.stderr)
        return 1
    mode = "applied" if args.apply else "dry-run"
    print(
        f"{mode}: verified {verified} encrypted token(s); rewrapped {rewrapped} under key version {kek_version()}"
    )
    if not args.apply:
        print("No database changes made. Pass --apply to persist this tenant's rotation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
