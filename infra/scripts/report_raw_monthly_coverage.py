#!/usr/bin/env python3
"""Export a tenant/source monthly row-count report for landed raw datasets."""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

# Fixed allowlist: only report-grained raw tables belong in this coverage report.
REPORT_SOURCES = (
    "raw_ads_sp_campaign_daily",
    "raw_ads_sp_placement_daily",
    "raw_ads_sp_ad_group_daily",
    "raw_ads_sp_keyword_daily",
    "raw_ads_sp_search_term_daily",
    "raw_ads_advertised_product_daily",
    "raw_ads_sp_purchased_product_daily",
    "raw_sales_traffic_asin_daily",
    "raw_sqp_query_snapshot",
)


def coverage_sql() -> str:
    source_rows = ",\n        ".join(f"('{source}')" for source in REPORT_SOURCES)
    source_counts = "\n        union all\n        ".join(
        f"""select tenant_id, date_trunc('month', report_date)::date as month_start,
                   '{source}'::text as source, count(*)::bigint as row_count,
                   max(report_date)::date as latest_report_date
            from raw.{source}
            group by tenant_id, date_trunc('month', report_date)::date"""
        for source in REPORT_SOURCES
    )
    return f"""with sources(source) as (
        values {source_rows}
    ), tenant_months as (
        select t.id as tenant_id, month_start::date as month_start
        from public.tenant t
        cross join lateral generate_series(
            date_trunc('month', t.created_at at time zone 'UTC'),
            date_trunc('month', current_timestamp at time zone 'UTC') - interval '1 month',
            interval '1 month'
        ) as months(month_start)
    ), counts as (
        {source_counts}
    )
    select tm.tenant_id::text as tenant_id, tm.month_start,
           s.source, coalesce(c.row_count, 0)::bigint as row_count,
           c.latest_report_date
    from tenant_months tm
    cross join sources s
    left join counts c
      on c.tenant_id = tm.tenant_id
     and c.month_start = tm.month_start
     and c.source = s.source
    order by tm.tenant_id, tm.month_start, s.source"""


def write_report(output_dir: Path, database_url: str) -> tuple[Path, int]:
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = output_dir / f"raw-monthly-coverage-{stamp}.csv"
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=output_dir
    )
    temporary = Path(temporary_name)
    row_count = 0
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            writer = csv.writer(stream)
            writer.writerow(
                ["tenant_id", "month_start", "source", "row_count", "latest_report_date"]
            )
            with psycopg.connect(database_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    connection.execute("set transaction read only")
                    connection.execute("set local statement_timeout = '300s'")
                    can_bypass_rls = connection.execute(
                        "select rolsuper or rolbypassrls as allowed "
                        "from pg_roles where rolname = current_user"
                    ).fetchone()
                    if not can_bypass_rls or not can_bypass_rls["allowed"]:
                        raise ValueError(
                            "DATABASE_URL must use a read-only operator role with BYPASSRLS "
                            "to report complete cross-tenant coverage"
                        )
                    cursor = connection.execute(coverage_sql())
                    for row in cursor:
                        writer.writerow(
                            [
                                row["tenant_id"],
                                row["month_start"],
                                row["source"],
                                row["row_count"],
                                row["latest_report_date"],
                            ]
                        )
                        row_count += 1
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except (OSError, psycopg.Error, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"could not create raw coverage report: {exc}") from exc
    return destination, row_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        parser.error("DATABASE_URL is required")
    try:
        path, rows = write_report(args.output_dir, database_url)
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"raw monthly coverage report: {path} ({rows} tenant/source/month rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
