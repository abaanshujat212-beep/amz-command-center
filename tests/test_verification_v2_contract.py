from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "packages/db/migrations/0063_verification_v2_snapshots.sql").read_text()
SERVICE = (ROOT / "services/actions/verification.py").read_text()
QUERY = (ROOT / "apps/web/lib/queries-verification.ts").read_text()
PAGE = (ROOT / "apps/web/app/verification/page.tsx").read_text()


def test_snapshot_schema_is_tenant_scoped_idempotent_and_final_evidence_is_immutable():
    assert "unique(tenant_id,action_id,horizon_days)" in MIGRATION
    assert "foreign key(action_id,tenant_id)" in MIGRATION
    assert "force row level security" in MIGRATION
    assert "if old.status='COMPLETE'" in MIGRATION


def test_all_required_horizons_and_insufficient_data_are_explicit():
    assert "HORIZONS = (1, 3, 7, 14, 30)" in SERVICE
    assert "INSUFFICIENT_DATA" in SERVICE
    assert "WINDOW_NOT_MATURE" in SERVICE
    assert "status in ('applied','verified')" in SERVICE


def test_read_contract_exposes_ordered_snapshot_evidence():
    assert "action_verification_snapshot" in QUERY
    assert "order by s.horizon_days" in QUERY
    for value in ("metric_keys", "baseline", "observed", "data_through", "reason_code"):
        assert value in QUERY
    assert "[1,3,7,14,30]" in PAGE
    assert "insufficient data" in PAGE
