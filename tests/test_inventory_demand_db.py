"""Raw sales evidence must not invent zero-demand days or crash forecast reads."""

import json
import os
import re
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
LIB = Path(__file__).resolve().parents[1] / "apps/web/lib/inventory.ts"


@pytest.fixture
def demand_db():
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as db:
        tenant = uuid.uuid4()
        db.execute("insert into tenant(id,name,slug) values(%s,'Demand test',%s)",
                   (tenant, str(tenant)))
        location = db.execute(
            """insert into inventory_location(tenant_id,location_code,location_type,display_name)
               values(%s,'warehouse','own_warehouse','Warehouse') returning id""", (tenant,),
        ).fetchone()["id"]
        db.execute(
            """insert into inventory_position_snapshot
               (tenant_id,location_id,sku,source_type,source_reference,observed_at,available_qty)
               values(%s,%s,'SKU','manual','stock',now(),100)""", (tenant, location),
        )
        yield db, tenant
        db.rollback()


def sales(db, tenant, days=30, units=5, *, age_hours=0, key="units_ordered", first_day=1):
    record = {"sku": "SKU"}
    if key:
        record[key] = units
    db.execute(
        """insert into raw.raw_sales_traffic_asin_daily(tenant_id,report_date,entity_id,record,loaded_at)
           select %s,current_date-day_offset,'SKU',%s::jsonb,now()-(%s*interval '1 hour')
           from generate_series(%s::int,%s::int) as day_offset""",
        (tenant, json.dumps(record), age_hours, first_day, first_day + days - 1),
    )


def read(db, tenant):
    source = LIB.read_text().split("export async function inventoryForecastRead", 1)[1]
    sql = re.search(r"\(client, `(.*?)`", source, re.DOTALL).group(1)
    sql = sql.replace("$1", "%(tenant)s").replace("$2", "%(fresh_hours)s")
    row, = db.execute(sql, {"tenant": tenant, "fresh_hours": 72}).fetchall()
    return row


def test_partial_history_uses_observed_day_mean_without_zero_filling(demand_db):
    db, tenant = demand_db
    sales(db, tenant, days=14, units=5)
    row = read(db, tenant)
    assert row["observed_days"] == 14
    assert row["average_daily_demand"] == 5


@pytest.mark.parametrize("key", ["units_ordered", "unitsOrdered"])
def test_complete_observed_zero_sales_remain_known_zero(demand_db, key):
    db, tenant = demand_db
    sales(db, tenant, units=0, key=key)
    row = read(db, tenant)
    assert row["observed_days"] == 30
    assert row["average_daily_demand"] == 0
    assert row["invalid_demand_rows"] == 0
    assert row["sales_freshness"] == "current"


@pytest.mark.parametrize("units", [None, -2, "bad", "NaN", "Infinity", True, "2.5", "1" * 100])
def test_invalid_units_fail_closed_without_cast_errors(demand_db, units):
    db, tenant = demand_db
    sales(db, tenant, units=units)
    row = read(db, tenant)
    assert row["average_daily_demand"] is None
    assert row["invalid_demand_rows"] == 30


def test_missing_units_are_not_zero_sales(demand_db):
    db, tenant = demand_db
    sales(db, tenant, key=None)
    row = read(db, tenant)
    assert row["average_daily_demand"] is None
    assert row["invalid_demand_rows"] == 30


@pytest.mark.parametrize(("age", "expected"), [(96, "stale"), (-24, "unknown")])
def test_stale_and_future_sales_loads_are_explicit(demand_db, age, expected):
    db, tenant = demand_db
    sales(db, tenant, age_hours=age)
    row = read(db, tenant)
    assert row["sales_freshness"] == expected


def test_no_sales_remain_unknown_and_empty(demand_db):
    db, tenant = demand_db
    row = read(db, tenant)
    assert row["observed_days"] == 0
    assert row["average_daily_demand"] is None
    assert row["sales_freshness"] == "unknown"


def test_current_day_sales_are_excluded_from_settled_history(demand_db):
    db, tenant = demand_db
    sales(db, tenant, days=1, units=100, first_day=0)
    sales(db, tenant, days=30, units=5)
    row = read(db, tenant)
    assert row["observed_days"] == 30
    assert row["average_daily_demand"] == 5


def test_one_invalid_day_does_not_become_a_partial_known_total(demand_db):
    db, tenant = demand_db
    sales(db, tenant, days=29)
    sales(db, tenant, days=1, first_day=30, units="bad")
    row = read(db, tenant)
    assert row["observed_days"] == 30
    assert row["invalid_demand_rows"] == 1
    assert row["average_daily_demand"] is None


def test_another_tenants_bad_sales_do_not_block_current_tenant(demand_db):
    db, tenant = demand_db
    other = uuid.uuid4()
    db.execute("insert into tenant(id,name,slug) values(%s,'Other demand',%s)", (other, str(other)))
    sales(db, tenant, units=5)
    sales(db, other, units="bad")
    row = read(db, tenant)
    assert row["invalid_demand_rows"] == 0
    assert row["average_daily_demand"] == 5
