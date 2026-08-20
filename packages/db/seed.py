"""Seed a local development tenant with the 8 starter rules.

    python -m packages.db.seed --name "Client A" --slug client-a

Safe to re-run: everything is upserted on (tenant_id, code) / slug.
Automation stays disabled and every rule stays in dry-run.
"""

from __future__ import annotations

import argparse
import json
import os

import psycopg
from psycopg.rows import dict_row

from services.rules.starter_rules import rule_rows

ADMIN_URL = os.environ.get(
    "DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty"
)


def seed(name: str, slug: str) -> str:
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into tenant (name, slug)
                values (%s, %s)
                on conflict (slug) do update set name = excluded.name
                returning id
                """,
                (name, slug),
            )
            tenant_id = cur.fetchone()["id"]

            cur.execute(
                """
                insert into tenant_settings (tenant_id)
                values (%s)
                on conflict (tenant_id) do nothing
                """,
                (tenant_id,),
            )

            inserted = 0
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
                inserted += 1

        conn.commit()

    print(f"tenant {slug} ({tenant_id}) seeded with {inserted} rules")
    print("automation_enabled=false, every rule enabled=false dry_run=true")
    return str(tenant_id)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="Dev Tenant")
    p.add_argument("--slug", default="dev")
    args = p.parse_args()
    seed(args.name, args.slug)
