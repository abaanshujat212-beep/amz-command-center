"""Search Query Performance CSV import seam."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")


def _int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(float(str(value).replace(",", "")))


def parse_row(raw: dict[str, str | None]) -> dict:
    asin = raw.get("asin") or raw.get("ASIN")
    query = raw.get("search_query") or raw.get("Search Query") or raw.get("query")
    report_date = raw.get("report_date") or raw.get("Report Date") or raw.get("date")
    if not asin or not query or not report_date:
        raise ValueError("asin, search_query and report_date are required")
    return {
        "asin": asin.strip(),
        "search_query": query.strip().lower(),
        "report_date": dt.date.fromisoformat(report_date[:10]),
        "query_volume": _int(raw.get("query_volume") or raw.get("Query Volume")),
        "impressions": _int(raw.get("impressions") or raw.get("Impressions")),
        "clicks": _int(raw.get("clicks") or raw.get("Clicks")),
        "cart_adds": _int(raw.get("cart_adds") or raw.get("Cart Adds")),
        "purchases": _int(raw.get("purchases") or raw.get("Purchases")),
        "query_rank": _int(raw.get("query_rank") or raw.get("Query Rank")),
        "record": raw,
    }


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [parse_row(row) for row in csv.DictReader(handle)]


def upsert_rows(conn, tenant_id: str, rows: list[dict]) -> int:
    for row in rows:
        conn.execute(
            """
            insert into raw.raw_sqp_query_snapshot (
                tenant_id, asin, search_query, report_date, query_volume,
                impressions, clicks, cart_adds, purchases, query_rank, record
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (tenant_id, asin, search_query, report_date) do update set
                query_volume = excluded.query_volume,
                impressions = excluded.impressions,
                clicks = excluded.clicks,
                cart_adds = excluded.cart_adds,
                purchases = excluded.purchases,
                query_rank = excluded.query_rank,
                record = excluded.record,
                loaded_at = now()
            """,
            (
                tenant_id,
                row["asin"],
                row["search_query"],
                row["report_date"],
                row["query_volume"],
                row["impressions"],
                row["clicks"],
                row["cart_adds"],
                row["purchases"],
                row["query_rank"],
                psycopg.types.json.Jsonb(row["record"]),
            ),
        )
    return len(rows)


def import_sqp(tenant_id: str, path: Path, *, database_url: str = DATABASE_URL) -> int:
    rows = load_csv(path)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        loaded = upsert_rows(conn, tenant_id, rows)
        conn.commit()
        return loaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Import SQP query snapshot CSV")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    print(f"sqp rows loaded={import_sqp(args.tenant_id, args.csv_path)}")


if __name__ == "__main__":
    main()
