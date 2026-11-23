from pathlib import Path

ROOT=Path(__file__).parents[1]
MIGRATION=(ROOT/"packages/db/migrations/0072_native_control_state.sql").read_text()
WORKER=(ROOT/"services/actions/worker.py").read_text()

def test_native_control_evidence_is_tenant_scoped_and_append_only():
    lower=MIGRATION.lower()
    assert "force row level security" in lower
    assert "revoke update, delete, truncate" in lower
    assert "source_observed_at" in MIGRATION and "source_api_version" in MIGRATION
    assert "source_fingerprint" in MIGRATION

def test_worker_checks_native_controls_before_live_provider_dispatch():
    assert "validate_native_control_batch" in WORKER
    native=WORKER.index("actions = validate_native_control_batch")
    guard=WORKER.index("actions = validate_live_batch")
    client=WORKER.index("ads_client = load_ads_client", guard)
    assert native < guard < client

def test_approval_path_checks_native_control_evidence():
    approval=(ROOT/"apps/web/lib/approval-decision.ts").read_text()
    guard=(ROOT/"apps/web/lib/native-control-approval.ts").read_text()
    assert "nativeControlApprovalConflict" in approval
    assert "NATIVE_OPTIMIZATION_CONFLICT" in guard
    assert "campaign_native_control_state" in guard
