"""Seed local development tenants with the starter rules.

    python -m packages.db.seed                              # both dev tenants
    python -m packages.db.seed --name "Client A" --slug client-a   # just one

Two tenants are seeded by default, deliberately. The RLS isolation gate (#3)
needs a second tenant to have something it *fails* to read; with a single
tenant that test can pass while demonstrating nothing.

Two things about this file are load-bearing, both learned the hard way:

1. `tenant` has FORCE ROW LEVEL SECURITY, so the `tenant_self` policy applies
   to the table owner as well. `set_tenant()` must run *before* the insert, or
   the WITH CHECK compares against an unset `app.tenant_id` (NULL) and the row
   is rejected.
2. Tenant ids are therefore deterministic (uuid5 of the slug) rather than
   server-generated: you cannot call `set_tenant(id)` before the row exists if
   the database is the one choosing the id.

`set_config(..., true)` is transaction-local, so each tenant is seeded inside
one transaction and the tenant context is re-established after every commit.

Safe to re-run: tenants upsert on id, rules on (tenant_id, code). Automation
stays disabled and every rule stays in dry-run.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid

import psycopg
from psycopg.rows import dict_row

from services.rules.starter_rules import rule_rows

ADMIN_URL = os.environ.get(
    "DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty"
)

# Stable namespace so `make seed` produces the same ids on every machine and
# tests can hard-code the fixture tenants without reading the database first.
SEED_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "seed.axaty.local")

DEV_TENANTS = [
    ("Dev Tenant", "dev"),
    ("Isolation Fixture", "dev-b"),
]


def tenant_id_for(slug: str) -> uuid.UUID:
    """Deterministic tenant id. Same slug always means the same tenant."""
    return uuid.uuid5(SEED_NAMESPACE, slug)


def seed_tenant(conn, name: str, slug: str) -> uuid.UUID:
    tenant_id = tenant_id_for(slug)

    with conn.cursor() as cur:
        # Must come first: FORCE RLS applies tenant_self to the owner too.
        cur.execute("select set_tenant(%s)", (str(tenant_id),))

        cur.execute(
            """
            insert into tenant (id, name, slug)
            values (%s, %s, %s)
            on conflict (id) do update set name = excluded.name
            """,
            (str(tenant_id), name, slug),
        )

        cur.execute(
            """
            insert into tenant_settings (tenant_id)
            values (%s)
            on conflict (tenant_id) do nothing
            """,
            (str(tenant_id),),
        )

        rules = 0
        for row in rule_rows(str(tenant_id)):
            cur.execute(
                """
                insert into rule (tenant_id, code, name, description, enabled,
                                  dry_run, priority, scope, condition_jsonb,
                                  action_jsonb, lookback_days, min_clicks,
                                  min_impressions)
                values (%(tenant_id)s, %(code)s, %(name)s, %(description)s,
                        %(enabled)s, %(dry_run)s, %(priority)s, %(scope)s,
                        %(condition_jsonb)s, %(action_jsonb)s,
                        %(lookback_days)s, %(min_clicks)s, %(min_impressions)s)
                on conflict (tenant_id, code) do update set
                    name = excluded.name,
                    description = excluded.description,
                    condition_jsonb = excluded.condition_jsonb,
                    action_jsonb = excluded.action_jsonb,
                    updated_at = now()
                """,
                {
                    **row,
                    "condition_jsonb": json.dumps(row["condition_jsonb"]),
                    "action_jsonb": json.dumps(row["action_jsonb"]),
                },
            )
            rules += 1

    # Commit per tenant. This also clears app.tenant_id, which is why
    # set_tenant() is called again at the top of the next tenant.
    conn.commit()
    print(f"  {slug:<10} {tenant_id}  {rules} rules")
    return tenant_id


def seed(tenants: list[tuple[str, str]]) -> list[uuid.UUID]:
    print(f"seeding {len(tenants)} tenant(s):")
    ids = []
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as conn:
        for name, slug in tenants:
            ids.append(seed_tenant(conn, name, slug))

    print("\nautomation_enabled=false, every rule enabled=false dry_run=true")
    if len(ids) > 1:
        print("the second tenant exists so the RLS isolation test has a victim")
    return ids


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Seed development tenants.")
    p.add_argument("--name", help="seed a single named tenant instead of the dev pair")
    p.add_argument("--slug", help="slug for --name")
    args = p.parse_args()

    if bool(args.name) != bool(args.slug):
        raise SystemExit("--name and --slug must be given together")

    seed([(args.name, args.slug)] if args.name else DEV_TENANTS)
