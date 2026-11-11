"""Postgres regression coverage for snapshot response fields and paginated readiness."""

import os
import re
import uuid
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
LIB = Path(__file__).resolve().parents[1] / "apps/web/lib/inventory.ts"


@pytest.fixture
def inventory():
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as db:
        tenant = uuid.uuid4()
        db.execute("insert into tenant(id,name,slug) values(%s,'Snapshot read',%s)",
                   (tenant, str(tenant)))
        yield db, tenant
        db.rollback()


def add_position(db, tenant, location, *, age=0, state="current", quantity=5, active=True):
    location_id = db.execute(
        """insert into inventory_location(tenant_id,location_code,location_type,display_name,active)
           values(%s,%s,'own_warehouse',%s,%s) returning id""",
        (tenant, location, location, active),
    ).fetchone()["id"]
    observed = db.execute("select now() as ts").fetchone()["ts"] - timedelta(hours=age)
    snapshot_id = db.execute(
        """insert into inventory_position_snapshot
           (tenant_id,location_id,sku,source_type,source_reference,observed_at,available_qty,
            inbound_qty,freshness_state)
           values(%s,%s,'SKU','manual','fixture',%s,%s,100,%s) returning id""",
        (tenant, location_id, observed, quantity, state),
    ).fetchone()["id"]
    return str(snapshot_id), str(location_id)


def read_queries(db, tenant, *, page=1, location=None):
    source = LIB.read_text().split("export async function inventorySnapshotRead", 1)[1]
    source = source.split("export async function inventoryForecastRead", 1)[0]
    queries = re.findall(r"\(client, `(.*?)`", source, re.DOTALL)
    assert len(queries) == 2
    params = {"p1": tenant, "p2": None, "p3": location, "p4": 72, "p5": 1, "p6": page - 1}
    return [db.execute(re.sub(r"\$(\d+)", r"%(p\1)s", sql), params).fetchall()
            for sql in queries]


def test_snapshot_fields_match_public_camel_case_contract(inventory):
    db, tenant = inventory
    snapshot, location = add_position(db, tenant, "warehouse", quantity=None)
    rows, summary = read_queries(db, tenant)
    row, = rows
    assert row["snapshotId"] == snapshot
    assert row["locationId"] == location
    assert row["locationCode"] == "warehouse"
    assert row["sourceType"] == "manual"
    assert row["sourceReference"] == "fixture"
    assert row["availableQty"] is None
    assert row["inboundQty"] == 100
    assert row["reservedQty"] is None
    assert row["expectedAvailableAt"] is None
    assert row["observedAt"]
    assert "available_qty" not in row
    assert summary[0]["total"] == 1


@pytest.mark.parametrize("page", [1, 2, 10])
def test_freshness_totals_cover_all_matching_pages_including_empty_page(inventory, page):
    db, tenant = inventory
    add_position(db, tenant, "a-current")
    add_position(db, tenant, "b-old", age=96)
    add_position(db, tenant, "c-partial", state="partial")
    add_position(db, tenant, "d-future", age=-24)
    add_position(db, tenant, "inactive", state="unknown", active=False)
    rows, summaries = read_queries(db, tenant, page=page)
    summary, = summaries
    assert summary == {"total": 4, "current": 1, "stale": 1, "partial": 1, "unknown": 1}
    assert len(rows) == (0 if page == 10 else 1)
    if page == 1:
        assert rows[0]["freshness"] == "current"


def test_summary_filters_match_snapshot_filters_and_exclude_other_tenants(inventory):
    db, tenant = inventory
    add_position(db, tenant, "warehouse")
    add_position(db, tenant, "stale", state="stale")
    other = uuid.uuid4()
    db.execute("insert into tenant(id,name,slug) values(%s,'Other',%s)", (other, str(other)))
    add_position(db, other, "warehouse", state="partial")
    rows, summary = read_queries(db, tenant, location="warehouse")
    assert len(rows) == 1
    assert summary == [{"total": 1, "current": 1, "stale": 0, "partial": 0, "unknown": 0}]
    rows, summary = read_queries(db, tenant, location="absent")
    assert rows == []
    assert summary == [{"total": 0, "current": 0, "stale": 0, "partial": 0, "unknown": 0}]
