from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "packages/db/migrations/0070_action_experiments.sql").read_text()
SERVICE = (ROOT / "apps/web/lib/action-experiments.ts").read_text()
ROUTE = (ROOT / "apps/web/app/api/verification/experiments/route.ts").read_text()


def test_experiments_are_tenant_scoped_audited_and_outcomes_append_only():
    assert MIGRATION.count("enable row level security") == 2
    assert MIGRATION.count("force row level security") == 2
    assert "grant select,insert on action_experiment_outcome" in MIGRATION
    assert "grant select,insert,update on action_experiment to axaty_app" in MIGRATION
    assert "action_experiment.created" in SERVICE
    assert "action_experiment.outcome_recorded" in SERVICE


def test_verified_action_learning_requires_same_entity_complete_unconfounded_evidence():
    assert "evidence.confounding_status === \"CONFOUNDED\"" in SERVICE
    assert "evidence.status !== \"COMPLETE\"" in SERVICE
    assert "Linked action must target the experiment entity" in SERVICE
    assert "outcome must match its unconfounded verification snapshot" in SERVICE
    assert "metricName !== definition?.success_metric" in SERVICE


def test_experiment_api_uses_authenticated_tenant_context_and_manager_writes():
    assert "currentContext()" in ROUTE
    assert "withTenant(actor.tenantId" in ROUTE
    assert "owner_or_admin_required" in ROUTE
    assert "tenantId, actor.userId, actor.role" in ROUTE
