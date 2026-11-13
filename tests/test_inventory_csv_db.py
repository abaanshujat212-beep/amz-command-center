"""CSV provenance, shared references and rollback use the actual intake SQL in CI."""

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


def run(db, name, values):
    sql = re.search(rf"const {name} = `(.*?)`", LIB.read_text(), re.DOTALL).group(1)
    sql = re.sub(r"\$(\d+)", r"%(p\1)s", sql)
    return db.execute(sql, {f"p{i}": value for i, value in enumerate(values, 1)}).fetchall()


@pytest.fixture
def csv_db():
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as db:
        tenant = uuid.uuid4()
        db.execute("insert into tenant(id,name,slug) values(%s,'CSV SQL test',%s)", (tenant, str(tenant)))
        db.execute("set local role axaty_app")
        db.execute("select set_config('app.tenant_id',%s,true)", (str(tenant),))
        location, = run(db, "CREATE_LOCATION_SQL", [tenant, "warehouse", "Warehouse"])
        yield db, tenant, location["id"]
        db.rollback()


def values(tenant, location, reference="csv-1"):
    return [tenant, reference, location, "SKU", "2026-01-01T12:00:00Z", "current",
            None, "0", None, None, None, None, None, None, None,
            json.dumps({"enteredBy": "actor-1", "inputChannel": "csv"}), "csv_import"]


def reference_values(tenant, reference="csv-1", source="csv_import"):
    return [tenant, reference, "warehouse", "Warehouse", "SKU", "2026-01-01T12:00:00Z", "current",
            None, "0", None, None, None, None, None, None, None, source]


def test_csv_source_and_actor_provenance_keep_unknown_and_zero(csv_db):
    db, tenant, location = csv_db
    inserted, = run(db, "INSERT_SNAPSHOT_SQL", values(tenant, location))
    row = db.execute("select source_type,source_payload,available_qty,on_hand_qty from inventory_position_snapshot where id=%s", (inserted["snapshotId"],)).fetchone()
    assert row["source_type"] == "csv_import"
    assert row["source_payload"] == {"enteredBy": "actor-1", "inputChannel": "csv"}
    assert row["available_qty"] == 0
    assert row["on_hand_qty"] is None
    assert run(db, "INSERT_SNAPSHOT_SQL", values(tenant, location)) == []


def test_reference_lookup_includes_both_sources_but_requires_exact_source_match(csv_db):
    db, tenant, location = csv_db
    run(db, "INSERT_SNAPSHOT_SQL", values(tenant, location))
    exact, = run(db, "EXISTING_SNAPSHOT_SQL", reference_values(tenant))
    manual, = run(db, "EXISTING_SNAPSHOT_SQL", reference_values(tenant, source="manual"))
    assert exact["matches"] is True
    assert manual["snapshotId"] == exact["snapshotId"]
    assert manual["matches"] is False


def test_batch_transaction_rolls_back_new_location_and_earlier_row_after_conflict(csv_db):
    db, tenant, location = csv_db
    run(db, "INSERT_SNAPSHOT_SQL", values(tenant, location, "existing"))
    with pytest.raises(ValueError, match="conflicting row"):
        with db.transaction():
            created, = run(db, "CREATE_LOCATION_SQL", [tenant, "batch-created", "Batch created"])
            run(db, "INSERT_SNAPSHOT_SQL", values(tenant, created["id"], "batch-row"))
            conflict = reference_values(tenant, "existing")
            conflict[8] = "7"
            row, = run(db, "EXISTING_SNAPSHOT_SQL", conflict)
            assert row["matches"] is False
            raise ValueError("conflicting row")
    assert db.execute("select count(*)::int total from inventory_position_snapshot").fetchone()["total"] == 1
    assert run(db, "LOCATION_SQL", [tenant, "batch-created"]) == []


def test_csv_reference_and_location_reads_remain_rls_scoped(csv_db):
    db, tenant, location = csv_db
    run(db, "INSERT_SNAPSHOT_SQL", values(tenant, location))
    db.execute("select set_config('app.tenant_id',%s,true)", (str(uuid.uuid4()),))
    assert run(db, "EXISTING_SNAPSHOT_SQL", reference_values(tenant)) == []
    assert run(db, "LOCATION_SQL", [tenant, "warehouse"]) == []
