from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0039_scheduled_report_delivery.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0039_scheduled_report_delivery.sql").read_text()
ROUTER = (ROOT / "packages/db/migrations/0034_notification_router_core.sql").read_text()


def test_schedule_migration_is_sequential_tenant_scoped_and_reversible():
    assert UP.startswith("-- 0039_scheduled_report_delivery.sql")
    assert "force row level security" in UP
    assert "create policy tenant_isolation on report_delivery_schedule" in UP
    assert "create policy tenant_isolation on report_delivery_run" in UP
    assert "drop table if exists report_delivery_run" in DOWN
    assert "drop table if exists report_delivery_schedule" in DOWN


def test_report_delivery_reuses_canonical_attempt_retry_cost_ledger():
    assert "create table notification_delivery" not in UP
    assert "references notification_event(id, tenant_id)" in UP
    for field in ("attempt integer", "retry_eligible boolean", "cost_amount numeric"):
        assert field in ROUTER
    for state in ("'RETRYABLE'", "'DEAD_LETTER'"):
        assert state in ROUTER


def test_report_worker_is_allowed_by_both_constraint_and_alert_bridge():
    assert "'internal','report_worker'" in UP
    assert "v_source not in (" in UP
    assert "'scheduler','action_worker','inventory_engine','internal','report_worker'" in UP
