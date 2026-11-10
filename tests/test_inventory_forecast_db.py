"""Execute the web forecast's actual SQL against multi-location inventory fixtures."""

import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
LIB = Path(__file__).resolve().parents[1] / "apps/web/lib/inventory.ts"


def forecast_rows(db, tenant_id):
    source = LIB.read_text().split("export async function inventoryForecastRead", 1)[1]
    sql = re.search(r"\(client, `(.*?)`", source, re.DOTALL).group(1)
    sql = sql.replace("$1", "%(tenant)s").replace("$2", "%(fresh_hours)s")
    return db.execute(sql, {"tenant": tenant_id, "fresh_hours": 72}).fetchall()


@pytest.fixture
def inventory_db():
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as db:
        tenant = uuid.uuid4()
        db.execute("insert into tenant(id,name,slug) values(%s,'Forecast test',%s)",
                   (tenant, str(tenant)))
        yield db, tenant
        db.rollback()


def position(db, tenant, location, quantity, *, age_hours=0, state="current", active=True):
    location_id = db.execute(
        """insert into inventory_location(tenant_id,location_code,location_type,display_name,active)
           values(%s,%s,'own_warehouse',%s,%s)
           on conflict (tenant_id,location_code) do update set active=excluded.active returning id""",
        (tenant, location, location, active),
    ).fetchone()["id"]
    observed = db.execute("select now() as ts").fetchone()["ts"] - timedelta(hours=age_hours)
    db.execute(
        """insert into inventory_position_snapshot
           (tenant_id,location_id,sku,source_type,source_reference,observed_at,available_qty,freshness_state)
           values(%s,%s,'SKU','manual',%s,%s,%s,%s)""",
        (tenant, location_id, str(uuid.uuid4()), observed, quantity, state),
    )


@pytest.mark.parametrize("quantity", [None, 0, 20])
def test_unknown_location_quantity_does_not_become_known_total(inventory_db, quantity):
    db, tenant = inventory_db
    position(db, tenant, "a", 10)
    position(db, tenant, "b", quantity)
    row, = forecast_rows(db, tenant)
    assert row["available_qty"] == (None if quantity is None else 10 + quantity)


@pytest.mark.parametrize(
    ("age", "state", "expected"),
    [(96, "current", "stale"), (-24, "current", "unknown"),
     (0, "partial", "partial"), (0, "unknown", "unknown"), (0, "stale", "stale")],
)
def test_fresh_location_cannot_mask_an_unready_location(inventory_db, age, state, expected):
    db, tenant = inventory_db
    position(db, tenant, "a", 10)
    position(db, tenant, "b", 20, age_hours=age, state=state)
    row, = forecast_rows(db, tenant)
    assert row["freshness_state"] == expected


def test_only_latest_active_tenant_positions_contribute(inventory_db):
    db, tenant = inventory_db
    position(db, tenant, "a", None, age_hours=96, state="partial")
    position(db, tenant, "a", 10)
    position(db, tenant, "inactive", None, age_hours=96, active=False)
    other = uuid.uuid4()
    db.execute("insert into tenant(id,name,slug) values(%s,'Other',%s)", (other, str(other)))
    position(db, other, "a", 500)
    row, = forecast_rows(db, tenant)
    assert row["available_qty"] == 10
    assert row["freshness_state"] == "current"


def test_aggregate_timestamp_exposes_oldest_contributing_observation(inventory_db):
    db, tenant = inventory_db
    position(db, tenant, "a", 10)
    position(db, tenant, "b", 20, age_hours=48)
    row, = forecast_rows(db, tenant)
    assert row["freshness_state"] == "current"
    observed = datetime.fromisoformat(row["observed_at"])
    assert (datetime.now(UTC) - observed).total_seconds() >= 48 * 3600
