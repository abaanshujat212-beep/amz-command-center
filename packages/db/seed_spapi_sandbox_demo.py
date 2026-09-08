"""Load clearly labelled local demo rows for the SP-API static sandbox.

Amazon's Reports sandbox returns fixed contract examples rather than seller
Sales & Traffic data.  This seed makes the local UI demonstrable without ever
pretending those rows came from a real seller account.  It is deliberately
guarded and refuses to run unless both the configured endpoint and stored
selling account are sandbox values.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from packages.db.seed import tenant_id_for

SANDBOX_HOST = "sandbox.sellingpartnerapi-"
FIXTURE_NOTE = "SP-API sandbox demo fixture — not real Amazon data"
PRODUCTS = (
    ("B0SANDBOX01", "SANDBOX-SKU-01", "Sandbox Bamboo Drawer Organiser", "Demo Home", 29.99, 24, 318),
    ("B0SANDBOX02", "SANDBOX-SKU-02", "Sandbox Stainless Water Bottle", "Demo Active", 18.50, 17, 245),
    ("B0SANDBOX03", "SANDBOX-SKU-03", "Sandbox Pet Grooming Brush", "Demo Pets", 14.95, 11, 176),
)


def _require_sandbox(conn, tenant_id: str) -> None:
    endpoint = os.environ.get("SPAPI_ENDPOINT", "").lower()
    if SANDBOX_HOST not in endpoint:
        raise RuntimeError("Refusing demo seed: SPAPI_ENDPOINT is not an Amazon sandbox host")
    row = conn.execute(
        """
        select 1
          from amazon_connection c
          join selling_account s on s.connection_id = c.id and s.tenant_id = c.tenant_id
         where c.tenant_id = %s and c.provider = 'sp_api'
           and s.selling_partner_id = 'sandbox'
        """,
        (tenant_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Refusing demo seed: tenant has no sandbox selling account")


def seed_sandbox_demo(*, tenant_slug: str = "dev", today: dt.date | None = None) -> int:
    load_dotenv(".env", override=False)
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty"
    )
    tenant_id = str(tenant_id_for(tenant_slug))
    today = today or dt.date.today()
    newest = today - dt.timedelta(days=1)
    loaded = 0

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        _require_sandbox(conn, tenant_id)

        for product_index, (asin, sku, title, brand, price, units, sessions) in enumerate(
            PRODUCTS
        ):
            for day_offset in range(14):
                report_date = newest - dt.timedelta(days=day_offset)
                daily_units = max(1, units - day_offset % 4 - product_index)
                daily_sessions = sessions - (day_offset * 3) + product_index * 9
                record = {
                    "data_source": "sandbox_demo_fixture",
                    "child_asin": asin,
                    "sku": sku,
                    "units_ordered": daily_units,
                    "ordered_product_sales": round(daily_units * price, 2),
                    "total_order_items": daily_units,
                    "sessions": daily_sessions,
                    "page_views": daily_sessions + 37,
                    "buy_box_percentage": 96 - product_index,
                    "unit_session_percentage": round(daily_units / daily_sessions * 100, 2),
                }
                conn.execute(
                    """
                    insert into raw.raw_sales_traffic_asin_daily
                        (tenant_id, report_date, entity_id, record)
                    values (%s, %s, %s, %s)
                    on conflict (tenant_id, report_date, entity_id) do update set
                        record = excluded.record, loaded_at = now()
                    """,
                    (tenant_id, report_date, asin, Jsonb(record)),
                )
                loaded += 1

            conn.execute(
                """
                insert into raw.raw_keepa_product_snapshot
                    (tenant_id, asin, captured_at, title, brand, buy_box_price,
                     sales_rank, review_count, rating, offer_count, record)
                values (%s, %s, now(), %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    asin,
                    title,
                    brand,
                    price,
                    18000 + product_index * 21000,
                    420 - product_index * 80,
                    4.6 - product_index * 0.2,
                    2 + product_index,
                    Jsonb({"data_source": "sandbox_demo_fixture"}),
                ),
            )
            conn.execute(
                """
                insert into sku_cost_ledger
                    (tenant_id, sku, asin, valid_from, cogs, freight_in,
                     fba_fee, storage_est, currency, note)
                values (%s, %s, %s, %s, %s, %s, %s, %s, 'GBP', %s)
                on conflict (tenant_id, sku) where valid_to is null do update set
                    asin = excluded.asin, cogs = excluded.cogs,
                    freight_in = excluded.freight_in, fba_fee = excluded.fba_fee,
                    storage_est = excluded.storage_est, note = excluded.note
                """,
                (
                    tenant_id,
                    sku,
                    asin,
                    newest - dt.timedelta(days=30),
                    6.25 + product_index,
                    0.70,
                    3.10,
                    0.18,
                    FIXTURE_NOTE,
                ),
            )

        conn.execute(
            """
            insert into pipeline_run
                (tenant_id, dataset, date_from, date_to, finished_at, status, rows_loaded)
            values (%s, 'sales_traffic_asin_daily', %s, %s, now(), 'success', %s)
            """,
            (tenant_id, newest - dt.timedelta(days=13), newest, loaded),
        )
        conn.commit()

    print(f"Loaded {loaded} clearly labelled sandbox demo Sales & Traffic rows")
    return loaded


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load guarded SP-API sandbox demo rows")
    parser.add_argument("--tenant-slug", default=os.environ.get("DEV_TENANT_SLUG", "dev"))
    args = parser.parse_args()
    seed_sandbox_demo(tenant_slug=args.tenant_slug)
