"""Static safety contract for the canonical tenant guardrail settings UI."""
from pathlib import Path

ROOT = Path(__file__).parents[1]
ACTIONS = (ROOT / "apps/web/app/settings/client/actions.ts").read_text()
PAGE = (ROOT / "apps/web/app/settings/client/page.tsx").read_text()

FIELDS = (
    "automation_enabled", "dry_run", "target_acos_default", "max_change_pct",
    "cooldown_days", "max_changes_per_day", "max_budget_increase_per_day",
    "blast_radius_pct", "min_bid", "max_bid", "max_daily_budget",
    "max_data_age_hours", "settlement_lag_days",
)


def test_every_enforced_guardrail_is_read_written_and_audited():
    for field in FIELDS:
        assert field in ACTIONS
        assert field in PAGE
    assert "before[0]" in ACTIONS
    assert "JSON.stringify(after)" in ACTIONS
    assert "tenant.settings_updated" in ACTIONS


def test_guardrail_write_keeps_rbac_and_tenant_scope():
    assert "mayManageTenant(actor.role)" in ACTIONS
    assert "withTenant(actor.tenantId" in ACTIONS
    assert "where tenant_id=$1" in ACTIONS


def test_ui_keeps_safe_defaults_and_explains_live_transition():
    assert "Automation remains opt-in" in PAGE
    assert "Dry-run only" in PAGE
    assert "permits supported live mutations" in PAGE
    assert "disabled={!editable}" in PAGE
