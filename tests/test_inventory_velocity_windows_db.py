"""Execute the forecast SQL against sparse, invalid and boundary-date demand evidence."""

import json
import os
import re
import uuid
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
LIB = Path(__file__).resolve().parents[1] / "apps/web/lib/inventory.ts"


@pytest.fixture
def velocity_db():
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as db:
        tenant = uuid.uuid4()
        db.execute("insert into tenant(id,name,slug) values(%s,'Velocity test',%s)", (tenant, str(tenant)))
        location = db.execute(
            """insert into inventory_location(tenant_id,location_code,location_type,display_name)
               values(%s,'warehouse','own_warehouse','Warehouse') returning id""", (tenant,),
        ).fetchone()["id"]
        db.execute(
            """insert into inventory_position_snapshot
               (tenant_id,location_id,sku,source_type,source_reference,observed_at,available_qty)
               values(%s,%s,'SKU','manual','stock',now(),100)""", (tenant, location),
        )
        as_of = db.execute("select (now() at time zone 'UTC')::date as day").fetchone()["day"]
        yield db, tenant, as_of
        db.rollback()


def sales(db, tenant, as_of, days, units, *, entity="SKU", age=0):
    for offset in days:
        db.execute(
            """insert into raw.raw_sales_traffic_asin_daily(tenant_id,report_date,entity_id,record,loaded_at)
               values(%s,%s,%s,%s::jsonb,now()-(%s*interval '1 hour'))""",
            (tenant, as_of - timedelta(days=offset), entity, json.dumps({"sku": "SKU", "units_ordered": units}), age),
        )


def read(db, tenant, *, clock=None):
    source = LIB.read_text().split("export async function inventoryForecastRead", 1)[1]
    sql = re.search(r"\(client, `(.*?)`", source, re.DOTALL).group(1)
    sql = sql.replace("$1", "%(tenant)s").replace("$2", "%(fresh_hours)s")
    # Fix only the explicit clock CTE for a deterministic year boundary; execute
    # every real aggregation/filter unchanged against those report dates.
    if clock is not None:
        sql = sql.replace("(now() at time zone 'UTC')::date as as_of_day", "%(clock)s::date as as_of_day")
    return db.execute(sql, {"tenant": tenant, "fresh_hours": 72, "clock": clock}).fetchone()


def test_no_data_stays_unknown_in_all_windows(velocity_db):
    db, tenant, as_of = velocity_db
    windows = read(db, tenant)["velocity_windows"]
    for days in (7, 14, 30):
        window = windows[f"{days}d"]
        assert window["windowDays"] == days
        assert window["startDay"] == (as_of - timedelta(days=days)).isoformat()
        assert window["endDay"] == (as_of - timedelta(days=1)).isoformat()
        assert window["observedDays"] == 0
        assert window["missingDays"] == days
        assert window["coverage"] == 0
        assert window["status"] == "no_data"
        assert window["unitsObserved"] is None
        assert window["averageDailyUnitsObserved"] is None
        assert window["salesFreshness"] == "unknown"
        assert window["salesLoadedAt"] is None


def test_complete_zero_and_partial_observed_mean_are_distinct(velocity_db):
    db, tenant, as_of = velocity_db
    sales(db, tenant, as_of, range(1, 8), 0)
    windows = read(db, tenant)["velocity_windows"]
    assert windows["7d"]["status"] == "complete"
    assert windows["7d"]["unitsObserved"] == 0
    assert windows["7d"]["averageDailyUnitsObserved"] == 0
    assert windows["14d"]["status"] == "partial"
    assert windows["14d"]["coverage"] == 0.5
    assert windows["14d"]["unitsObserved"] == 0
    assert windows["30d"]["missingDays"] == 23


def test_same_sku_entities_aggregate_daily_without_inventing_observed_days(velocity_db):
    db, tenant, as_of = velocity_db
    sales(db, tenant, as_of, [1, 3], 2, entity="ASIN-A")
    sales(db, tenant, as_of, [1, 3], 3, entity="ASIN-B")
    window = read(db, tenant)["velocity_windows"]["7d"]
    assert window["observedDays"] == 2
    assert window["missingDays"] == 5
    assert window["unitsObserved"] == 10
    assert window["averageDailyUnitsObserved"] == 5
    assert window["status"] == "partial"


@pytest.mark.parametrize("units", [None, "bad", -1, True])
def test_one_invalid_row_invalidates_its_window_even_with_a_valid_same_day_row(velocity_db, units):
    db, tenant, as_of = velocity_db
    sales(db, tenant, as_of, [1], 5, entity="good")
    sales(db, tenant, as_of, [1], units, entity="bad")
    windows = read(db, tenant)["velocity_windows"]
    for window in windows.values():
        assert window["observedDays"] == 1
        assert window["invalidRows"] == 1
        assert window["status"] == "invalid"
        assert window["unitsObserved"] is None
        assert window["averageDailyUnitsObserved"] is None


def test_invalid_rows_outside_recent_window_do_not_erase_recent_evidence(velocity_db):
    db, tenant, as_of = velocity_db
    sales(db, tenant, as_of, range(1, 8), 5)
    sales(db, tenant, as_of, [8], "bad")
    windows = read(db, tenant)["velocity_windows"]
    assert windows["7d"]["status"] == "complete"
    assert windows["7d"]["unitsObserved"] == 35
    assert windows["14d"]["status"] == "invalid"
    assert windows["30d"]["status"] == "invalid"


@pytest.mark.parametrize(("age", "expected"), [(96, "stale"), (-24, "unknown")])
def test_freshness_is_scoped_to_each_window(velocity_db, age, expected):
    db, tenant, as_of = velocity_db
    sales(db, tenant, as_of, [1], 5, age=age)
    sales(db, tenant, as_of, [8], 5, age=0)
    windows = read(db, tenant)["velocity_windows"]
    assert windows["7d"]["salesFreshness"] == expected
    assert windows["14d"]["salesFreshness"] == ("unknown" if age < 0 else "current")
    assert windows["7d"]["salesLoadedAt"].endswith("Z")


def test_future_load_among_current_rows_remains_unknown(velocity_db):
    db, tenant, as_of = velocity_db
    sales(db, tenant, as_of, [1], 5, entity="current")
    sales(db, tenant, as_of, [1], 5, entity="future", age=-1)
    assert read(db, tenant)["velocity_windows"]["7d"]["salesFreshness"] == "unknown"


def test_today_future_and_outside_window_dates_are_excluded(velocity_db):
    db, tenant, as_of = velocity_db
    sales(db, tenant, as_of, [0, -1, 31], 500)
    sales(db, tenant, as_of, [1, 7, 14, 30], 2)
    windows = read(db, tenant)["velocity_windows"]
    assert windows["7d"]["observedDays"] == 2
    assert windows["7d"]["unitsObserved"] == 4
    assert windows["14d"]["observedDays"] == 3
    assert windows["30d"]["observedDays"] == 4


def test_utc_window_boundaries_do_not_follow_database_session_timezone(velocity_db):
    db, tenant, as_of = velocity_db
    sales(db, tenant, as_of, [0, 1, 7, 8, 14, 30, 31], 2)
    baseline = read(db, tenant)["velocity_windows"]
    for timezone in ("Pacific/Kiritimati", "Etc/GMT+12"):
        db.execute("select set_config('TimeZone',%s,true)", (timezone,))
        assert read(db, tenant)["velocity_windows"] == baseline


def test_year_boundary_uses_completed_dates(velocity_db):
    db, tenant, _ = velocity_db
    clock = date(2026, 1, 1)
    sales(db, tenant, clock, [0, 1, 7, 8, 30, 31], 2)
    windows = read(db, tenant, clock=clock)["velocity_windows"]
    assert windows["7d"]["startDay"] == "2025-12-25"
    assert windows["7d"]["endDay"] == "2025-12-31"
    assert windows["7d"]["observedDays"] == 2
    assert windows["30d"]["startDay"] == "2025-12-02"
    assert windows["30d"]["observedDays"] == 4


def test_another_tenants_sales_never_enter_windows(velocity_db):
    db, tenant, as_of = velocity_db
    other = uuid.uuid4()
    db.execute("insert into tenant(id,name,slug) values(%s,'Other velocity',%s)", (other, str(other)))
    sales(db, tenant, as_of, [1], 5)
    sales(db, other, as_of, range(1, 31), "bad")
    window = read(db, tenant)["velocity_windows"]["7d"]
    assert window["observedDays"] == 1
    assert window["unitsObserved"] == 5
    assert window["invalidRows"] == 0


@pytest.mark.parametrize("units", ["9007199254740992", "5000000000000000"])
def test_unsafe_javascript_totals_remain_unknown_in_evidence_and_forecast(velocity_db, units):
    db, tenant, as_of = velocity_db
    sales(db, tenant, as_of, [1, 2], units)
    row = read(db, tenant)
    assert row["average_daily_demand"] is None
    assert row["numeric_range_exceeded"] is True
    for window in row["velocity_windows"].values():
        assert window["numericRangeExceeded"] is True
        assert window["status"] == "invalid"
        assert window["unitsObserved"] is None
        assert window["averageDailyUnitsObserved"] is None
