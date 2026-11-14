#!/usr/bin/env python3
"""Write a tenant-scoped settled PPC/commerce mart export for reconciliation."""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from uuid import UUID

FIELDS = (
    "report_date", "grain", "entity_id", "placement", "is_settled", "currency",
    "spend", "ad_sales", "ad_orders", "total_sales", "budget_amount",
)
ALLOWED_PLACEMENTS = {"top_of_search", "product_page", "rest_of_search", "off_amazon"}


def export_csv(database_url: str, tenant_id: UUID, start: date, end: date, output: Path) -> int:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("psycopg is required; install the project dependencies") from exc

    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".partial", dir=output.parent
    )
    temporary = Path(temporary_name)
    row_count = 0
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            with psycopg.connect(database_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    connection.execute("set transaction read only")
                    connection.execute("set local statement_timeout = '60s'")
                    connection.execute("select set_config('app.tenant_id', %s, true)", (str(tenant_id),))
                    role = connection.execute(
                        "select rolsuper or rolbypassrls as elevated "
                        "from pg_roles where rolname = current_user"
                    ).fetchone()
                    if not role or role["elevated"]:
                        raise ValueError(
                            "DATABASE_URL must use a non-superuser, non-BYPASSRLS read-only role"
                        )
                    tenant = connection.execute(
                        "select ts.currency from public.tenant_settings ts "
                        "where ts.tenant_id = %s",
                        (tenant_id,),
                    ).fetchone()
                    if not tenant:
                        raise ValueError("tenant was not found or is not visible to this database role")
                    currency = tenant["currency"]
                    if not isinstance(currency, str) or len(currency) != 3 or not currency.isupper():
                        raise ValueError("tenant currency is not an uppercase three-letter code")

                    queries = (
                        (
                            "campaign",
                            """select report_date, campaign_id as entity_id,
                                      cost as spend, attributed_sales_7d as ad_sales,
                                      attributed_orders_7d as ad_orders,
                                      budget_amount, is_settled
                               from copilot.mart_ppc_campaign_daily
                               where tenant_id = %s and report_date between %s and %s
                                 and is_settled
                               order by report_date, campaign_id""",
                        ),
                        (
                            "placement",
                            """select report_date, placement_entity_id as entity_id, placement,
                                      cost as spend, attributed_sales_7d as ad_sales,
                                      attributed_orders_7d as ad_orders, is_settled
                               from copilot.mart_ppc_placement_daily
                               where tenant_id = %s and report_date between %s and %s
                                 and is_settled
                               order by report_date, campaign_id, placement""",
                        ),
                        (
                            "account",
                            """select report_date, total_sales, is_settled
                               from copilot.mart_commerce_sales_daily
                               where tenant_id = %s and report_date between %s and %s
                                 and is_settled
                               order by report_date""",
                        ),
                    )
                    for grain, query in queries:
                        rows = connection.execute(query, (tenant_id, start, end))
                        for row in rows:
                            placement = row.get("placement") or ""
                            if grain == "placement" and placement not in ALLOWED_PLACEMENTS:
                                raise ValueError(
                                    f"unsupported mart placement {placement!r}; preserve it as a defect"
                                )
                            writer.writerow(
                                {
                                    "report_date": row["report_date"].isoformat(),
                                    "grain": grain,
                                    "entity_id": row["entity_id"] if grain != "account" else str(tenant_id),
                                    "placement": placement,
                                    "is_settled": str(row["is_settled"]).lower(),
                                    "currency": currency,
                                    "spend": row.get("spend"),
                                    "ad_sales": row.get("ad_sales"),
                                    "ad_orders": row.get("ad_orders"),
                                    "total_sales": row.get("total_sales"),
                                    "budget_amount": row.get("budget_amount"),
                                }
                            )
                            row_count += 1
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        os.chmod(output, 0o600)
    except (OSError, ValueError, psycopg.Error) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"could not export PPC marts: {exc}") from exc
    return row_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL_COPILOT", "")
    if not database_url:
        parser.error("DATABASE_URL_COPILOT is required")
    if args.end < args.start:
        parser.error("--end must be on or after --start")
    try:
        rows = export_csv(database_url, args.tenant_id, args.start, args.end, args.output)
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"PPC mart export: {args.output} ({rows} settled rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
