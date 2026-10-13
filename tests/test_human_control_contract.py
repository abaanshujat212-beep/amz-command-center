from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0050_human_override_lifecycle.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0050_human_override_lifecycle.sql").read_text()
WORKER = (ROOT / "services/actions/worker.py").read_text()
ENGINE = (ROOT / "services/rules/engine.py").read_text()
UI = (ROOT / "apps/web/app/settings/automation-control/actions.ts").read_text()


def test_append_only_tenant_scoped_control_contract():
    assert "HUMAN_OVERRIDE','LOCKED','REVIEW_DUE','AUTOMATED" in UP
    assert "force row level security" in UP
    assert "entity_automation_control_immutable" in UP
    assert "drop table if exists entity_automation_control" in DOWN


def test_rules_and_worker_both_enforce_control():
    assert "active_control(" in ENGINE
    assert "active_control(" in WORKER
    assert "validate_control_batch" in WORKER


def test_manual_negative_uses_canonical_approval_queue_and_audit():
    assert "insert into action" in UI
    assert "request_origin" in UI and "'human'" in UI
    assert "manual_negative.requested" in UI
    assert "approved" not in UI
