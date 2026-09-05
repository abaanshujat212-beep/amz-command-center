"""Seed one local tenant's SP-API sandbox connection from environment.

This script stores only encrypted refresh tokens in the database. Put the real
keys in .env locally; never commit a filled .env file.

Usage:
    python -m packages.db.seed_spapi_sandbox
    python -m packages.db.seed_spapi_sandbox --tenant-slug dev
"""

from __future__ import annotations

import argparse
import os

import psycopg
from psycopg.rows import dict_row

from packages.db.seed import tenant_id_for
from services.ingest.security.vault import seal

ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
DEFAULT_TENANT_SLUG = os.environ.get("DEV_TENANT_SLUG", "dev")


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} must be set in .env")
    return value


def seed_spapi_sandbox(*, tenant_slug: str = DEFAULT_TENANT_SLUG) -> str:
    tenant_id = str(tenant_id_for(tenant_slug))
    refresh_token = require_env("SPAPI_REFRESH_TOKEN")
    region = os.environ.get("SPAPI_REGION", "eu").strip() or "eu"
    seller_account_id = os.environ.get("SPAPI_SELLER_ACCOUNT_ID", "sandbox").strip() or "sandbox"
    marketplace_id = os.environ.get("MARKETPLACE_ID", "A1F83G8C2ARO7P").strip() or "A1F83G8C2ARO7P"
    sealed = seal(refresh_token)

    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        row = conn.execute(
            """
            insert into amazon_connection (
                tenant_id, provider, region, seller_account_id,
                refresh_token_encrypted, key_version, status
            )
            values (%s, 'sp_api', %s, %s, %s, %s, 'active')
            on conflict (tenant_id, provider, seller_account_id) do update set
                region = excluded.region,
                refresh_token_encrypted = excluded.refresh_token_encrypted,
                key_version = excluded.key_version,
                status = 'active',
                updated_at = now()
            returning id
            """,
            (tenant_id, region, seller_account_id, sealed.ciphertext, sealed.key_version),
        ).fetchone()
        conn.execute(
            """
            insert into selling_account (tenant_id, connection_id, marketplace_id, seller_id)
            values (%s, %s, %s, %s)
            on conflict (tenant_id, marketplace_id, seller_id) do update set
                connection_id = excluded.connection_id
            """,
            (tenant_id, row["id"], marketplace_id, seller_account_id),
        )
        conn.commit()
    print(f"SP-API sandbox connection ready for tenant {tenant_slug} ({tenant_id})")
    return tenant_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed SP-API sandbox credentials for one local tenant")
    parser.add_argument("--tenant-slug", default=DEFAULT_TENANT_SLUG)
    args = parser.parse_args()
    seed_spapi_sandbox(tenant_slug=args.tenant_slug)
