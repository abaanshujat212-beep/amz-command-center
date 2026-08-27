"""Keepa product snapshot ingestion seam."""

from __future__ import annotations

import argparse
import os
from typing import Iterable

import httpx
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
KEEPA_DOMAIN_UK = 2


def normalize_product(product: dict) -> dict:
    stats = product.get("stats") or {}
    asin = str(product.get("asin") or "")
    if not asin:
        raise ValueError("Keepa product missing asin")
    buy_box = stats.get("buyBoxPrice") or product.get("buyBoxPrice")
    if isinstance(buy_box, int | float) and buy_box > 0:
        buy_box = buy_box / 100
    return {
        "asin": asin,
        "title": product.get("title"),
        "brand": product.get("brand"),
        "buy_box_price": buy_box if buy_box and buy_box > 0 else None,
        "sales_rank": product.get("salesRank") or stats.get("salesRank"),
        "review_count": product.get("reviewCount") or stats.get("reviewCount"),
        "rating": (product.get("rating") or stats.get("rating")),
        "offer_count": product.get("offerCount") or stats.get("offerCount"),
        "record": product,
    }


class KeepaClient:
    def __init__(self, api_key: str, domain: int = KEEPA_DOMAIN_UK) -> None:
        self.api_key = api_key
        self.domain = domain

    def products(self, asins: Iterable[str]) -> list[dict]:
        response = httpx.get(
            "https://api.keepa.com/product",
            params={"key": self.api_key, "domain": self.domain, "asin": ",".join(asins), "stats": 30},
            timeout=60,
        )
        response.raise_for_status()
        return list((response.json()).get("products") or [])


def product_asins(conn, tenant_id: str, limit: int) -> list[str]:
    rows = conn.execute(
        """
        select distinct asin
          from raw.raw_sales_traffic_asin_daily
         where tenant_id = %s
         order by asin
         limit %s
        """,
        (tenant_id, limit),
    ).fetchall()
    return [r["asin"] for r in rows]


def upsert_products(conn, tenant_id: str, products: list[dict]) -> int:
    loaded = 0
    for product in products:
        row = normalize_product(product)
        conn.execute(
            """
            insert into raw.raw_keepa_product_snapshot (
                tenant_id, asin, title, brand, buy_box_price, sales_rank,
                review_count, rating, offer_count, record
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                row["asin"],
                row["title"],
                row["brand"],
                row["buy_box_price"],
                row["sales_rank"],
                row["review_count"],
                row["rating"],
                row["offer_count"],
                psycopg.types.json.Jsonb(row["record"]),
            ),
        )
        loaded += 1
    return loaded


def run(tenant_id: str, *, database_url: str = DATABASE_URL, client: KeepaClient | None = None, limit: int = 100) -> int:
    api_key = os.environ.get("KEEPA_API_KEY")
    if client is None:
        if not api_key:
            raise RuntimeError("KEEPA_API_KEY must be set")
        client = KeepaClient(api_key)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        asins = product_asins(conn, tenant_id, limit)
        loaded = upsert_products(conn, tenant_id, client.products(asins) if asins else [])
        conn.commit()
        return loaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Keepa product snapshots")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    print(f"keepa products loaded={run(args.tenant_id, limit=args.limit)}")


if __name__ == "__main__":
    main()
