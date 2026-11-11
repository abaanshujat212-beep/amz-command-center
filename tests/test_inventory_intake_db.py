"""Run manual-intake SQL with the application role and real RLS in required CI."""

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
LIB = Path(__file__).resolve().parents[1] / "apps/web/lib/inventory-intake.ts"


def sql(name):
    text = re.search(rf"const {name} = `(.*?)`", LIB.read_text(), re.DOTALL).group(1)
    return re.sub(r"\$(\d+)", r"%(p\1)s", text)


def run(db, name, values):
    return db.execute(sql(name), {f"p{i}": value for i, value in enumerate(values, 1)}).fetchall()


@pytest.fixture
def intake_db():
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as db:
        tenant = uuid.uuid4()
        db.execute("insert into tenant(id,name,slug) values(%s,'Intake SQL test',%s)", (tenant, str(tenant)))
        db.execute("set local role axaty_app")
        db.execute("select set_config('app.tenant_id',%s,true)", (str(tenant),))
        location, = run(db, "CREATE_LOCATION_SQL", [tenant, "warehouse", "Warehouse"])
        yield db, tenant, location["id"]
        db.rollback()


def snapshot_values(tenant, location):
    return [tenant, "count-1", location, "SKU", "2026-01-01T12:00:00Z", "current",
            None, "0", None, None, None, None, None, None, None, json.dumps({"enteredBy": "actor-1"})]


def reference_values(tenant):
    return [tenant, "count-1", "warehouse", "Warehouse", "SKU", "2026-01-01T12:00:00Z", "current",
            None, "0", None, None, None, None, None, None, None]


def test_manual_intake_is_append_only_and_exact_sql_retry_does_not_overwrite(intake_db):
    db, tenant, location = intake_db
    values = snapshot_values(tenant, location)
    inserted, = run(db, "INSERT_SNAPSHOT_SQL", values)
    assert run(db, "INSERT_SNAPSHOT_SQL", values) == []
    values[7] = "5"
    assert run(db, "INSERT_SNAPSHOT_SQL", values) == []
    row = db.execute("select source_type,available_qty,on_hand_qty,source_payload from inventory_position_snapshot where id=%s", (inserted["snapshotId"],)).fetchone()
    assert row["source_type"] == "manual"
    assert row["available_qty"] == 0
    assert row["on_hand_qty"] is None
    assert row["source_payload"] == {"enteredBy": "actor-1"}
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction():
            db.execute("update inventory_position_snapshot set available_qty=9 where id=%s", (inserted["snapshotId"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction():
            db.execute("delete from inventory_position_snapshot where id=%s", (inserted["snapshotId"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction():
            db.execute("delete from inventory_location where id=%s", (location,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction():
            db.execute("truncate inventory_location cascade")
    assert db.execute("select count(*)::int total from inventory_position_snapshot where id=%s", (inserted["snapshotId"],)).fetchone()["total"] == 1


def test_manual_reference_comparison_detects_conflicting_values_and_inactive_location(intake_db):
    db, tenant, location = intake_db
    run(db, "INSERT_SNAPSHOT_SQL", snapshot_values(tenant, location))
    values = reference_values(tenant)
    row, = run(db, "EXISTING_SNAPSHOT_SQL", values)
    assert row["matches"] is True
    values[8] = "1"
    row, = run(db, "EXISTING_SNAPSHOT_SQL", values)
    assert row["matches"] is False
    db.execute("update inventory_location set active=false where id=%s", (location,))
    row, = run(db, "EXISTING_SNAPSHOT_SQL", reference_values(tenant))
    assert row["active"] is False


def test_create_location_conflict_never_renames_or_reactivates(intake_db):
    db, tenant, location = intake_db
    db.execute("update inventory_location set active=false where id=%s", (location,))
    assert run(db, "CREATE_LOCATION_SQL", [tenant, "warehouse", "Replacement name"]) == []
    row, = run(db, "LOCATION_SQL", [tenant, "warehouse"])
    assert row["active"] is False
    assert row["display_name"] == "Warehouse"


def test_manual_intake_reads_remain_tenant_scoped(intake_db):
    db, tenant, location = intake_db
    run(db, "INSERT_SNAPSHOT_SQL", snapshot_values(tenant, location))
    other = uuid.uuid4()
    db.execute("select set_config('app.tenant_id',%s,true)", (str(other),))
    assert run(db, "LOCATION_SQL", [tenant, "warehouse"]) == []
    assert run(db, "EXISTING_SNAPSHOT_SQL", reference_values(tenant)) == []


@pytest.mark.parametrize(
    ("table", "privilege", "expected"),
    [("inventory_position_snapshot", "SELECT", True),
     ("inventory_position_snapshot", "INSERT", True),
     ("inventory_position_snapshot", "UPDATE", False),
     ("inventory_position_snapshot", "DELETE", False),
     ("inventory_position_snapshot", "TRUNCATE", False),
     ("inventory_location", "SELECT", True),
     ("inventory_location", "INSERT", True),
     ("inventory_location", "UPDATE", True),
     ("inventory_location", "DELETE", False),
     ("inventory_location", "TRUNCATE", False)],
)
def test_inventory_history_privileges_are_explicitly_limited(intake_db, table, privilege, expected):
    db, _, _ = intake_db
    row = db.execute("select has_table_privilege(current_user,%s,%s) allowed", (table, privilege)).fetchone()
    assert row["allowed"] is expected
