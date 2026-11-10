from datetime import UTC, datetime
from pathlib import Path

import pytest

from services.inventory.snapshots import save_location, save_snapshot

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "packages/db/migrations/0067_inventory_snapshot_foundation.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0067_inventory_snapshot_foundation.sql").read_text()


class Cursor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, params):
        self.queries.append((query, params))

    def fetchone(self):
        return self.responses.pop(0)


class Connection:
    def __init__(self, responses):
        self._cursor = Cursor(responses)

    def cursor(self):
        return self._cursor


def test_migration_has_tenant_scoped_append_only_snapshot_shape_and_down():
    assert "unique (id,tenant_id)" in MIGRATION
    assert "foreign key (location_id,tenant_id)" in MIGRATION
    assert "unique (tenant_id,source_type,source_reference,location_id,sku,observed_at)" in MIGRATION
    assert "enable row level security" in MIGRATION
    assert "force row level security" in MIGRATION
    assert "on_hand_qty numeric(16,4) check (on_hand_qty >= 0)" in MIGRATION
    assert "available_qty numeric(16,4) check (available_qty >= 0)" in MIGRATION
    assert "drop table if exists inventory_position_snapshot" in DOWN
    assert "drop table if exists inventory_location" in DOWN


def test_location_creation_is_tenant_scoped_and_idempotent():
    conn = Connection([{"id": "location-id"}])
    location_id = save_location(
        conn, tenant_id="tenant-1", location_code="warehouse-a", location_type="own_warehouse",
        display_name="Warehouse A",
    )
    sql, params = conn._cursor.queries[0]
    assert "on conflict (tenant_id,location_code)" in sql
    assert params[:3] == ("tenant-1", "warehouse-a", "own_warehouse")
    assert location_id == "location-id"


def test_missing_quantities_stay_null_and_import_is_idempotent():
    conn = Connection([{"id": "snapshot-id"}])
    snapshot_id, inserted = save_snapshot(
        conn, tenant_id="tenant-1", location_id="location-1", sku="SKU-1",
        source_type="csv_import", source_reference="upload-42:row-1",
        observed_at=datetime(2026, 11, 10, tzinfo=UTC),
        available_qty=0,
    )
    sql, params = conn._cursor.queries[0]
    assert "on conflict (tenant_id,source_type,source_reference,location_id,sku,observed_at)" in sql
    assert "do nothing returning id" in sql
    assert snapshot_id == "snapshot-id"
    assert inserted is True
    assert params[8] is None  # missing on-hand stays unknown
    assert params[9] == 0  # explicitly supplied zero remains zero


def test_duplicate_snapshot_returns_original_id_without_mutation():
    conn = Connection([None, {"id": "existing"}])
    result = save_snapshot(
        conn, tenant_id="t", location_id="l", sku="s", source_type="manual",
        source_reference="manual-observation-1", observed_at=datetime(2026, 11, 10, tzinfo=UTC),
    )
    assert result == ("existing", False)
    assert len(conn._cursor.queries) == 2


def test_inventory_write_validation_preserves_provenance_and_unknowns():
    with pytest.raises(ValueError, match="marketplace"):
        save_location(
            Connection([]), tenant_id="t", location_code="fba", location_type="amazon_fba",
            display_name="FBA",
        )
    with pytest.raises(ValueError, match="source_provider_id"):
        save_snapshot(
            Connection([]), tenant_id="t", location_id="l", sku="s",
            source_type="approved_provider", source_reference="r",
            observed_at=datetime(2026, 11, 10, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="timezone"):
        save_snapshot(
            Connection([]), tenant_id="t", location_id="l", sku="s", source_type="manual",
            source_reference="r", observed_at=datetime(2026, 11, 10),
        )
    with pytest.raises(ValueError, match="nonnegative"):
        save_snapshot(
            Connection([]), tenant_id="t", location_id="l", sku="s", source_type="manual",
            source_reference="r", observed_at=datetime(2026, 11, 10, tzinfo=UTC), available_qty=-1,
        )
