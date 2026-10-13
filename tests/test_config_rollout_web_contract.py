from pathlib import Path

ROOT=Path(__file__).parents[1]
LIB=(ROOT/"apps/web/lib/config-rollouts.ts").read_text()
ACTIONS=(ROOT/"apps/web/app/settings/config-rollouts/actions.ts").read_text()
API=(ROOT/"apps/web/app/api/config-rollouts/route.ts").read_text()
def test_preview_is_tenant_scoped_and_never_queues_amazon_actions():
    assert "configuration_simulation" in LIB and "protected" in LIB
    assert "insert into action" not in LIB+ACTIONS+API
    assert "withTenant" in ACTIONS and "withTenant" in API
def test_rollout_requires_operator_reason_and_writes_audit():
    assert "reason" in ACTIONS and "audit_log" in ACTIONS
    assert "deterministicCanary" in ACTIONS
