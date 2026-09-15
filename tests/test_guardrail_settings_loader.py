from decimal import Decimal

import pytest

from services.rules.guardrails import TenantGuardConfig
from services.rules.settings import GuardrailConfigError, load_tenant_guard_config


class Cursor:
    def __init__(self, row):
        self.row = row
        self.query = None
        self.params = None

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchone(self):
        return self.row


def complete_row(**overrides):
    row = {
        "automation_enabled": True,
        "dry_run": False,
        "max_change_pct": Decimal("0.1250"),
        "cooldown_days": 5,
        "max_changes_per_day": 12,
        "max_budget_increase_per_day": Decimal("25.50"),
        "blast_radius_pct": Decimal("0.2000"),
        "min_bid": Decimal("0.05"),
        "max_bid": Decimal("3.50"),
        "max_daily_budget": Decimal("75.00"),
        "max_data_age_hours": 24,
        "settlement_lag_days": 4,
    }
    row.update(overrides)
    return row


def test_missing_row_returns_conservative_no_consent_defaults():
    cursor = Cursor(None)
    cfg = load_tenant_guard_config(cursor, "tenant-1")
    assert cfg == TenantGuardConfig()
    assert cfg.automation_enabled is False
    assert cfg.dry_run is True


def test_complete_row_overrides_every_guardrail_with_explicit_numeric_conversion():
    cursor = Cursor(complete_row())
    cfg = load_tenant_guard_config(cursor, "tenant-1")
    assert cursor.params == ("tenant-1",)
    assert "max_data_age_hours" in cursor.query
    assert "settlement_lag_days" in cursor.query
    assert cfg == TenantGuardConfig(
        automation_enabled=True,
        dry_run=False,
        max_change_pct=0.125,
        cooldown_days=5,
        max_changes_per_day=12,
        max_budget_increase_per_day=25.5,
        blast_radius_pct=0.2,
        min_bid=0.05,
        max_bid=3.5,
        max_daily_budget=75.0,
        max_data_age_hours=24,
        settlement_lag_days=4,
    )


@pytest.mark.parametrize(
    "row",
    [
        {key: value for key, value in complete_row().items() if key != "dry_run"},
        complete_row(max_change_pct=None),
        complete_row(automation_enabled=1),
        complete_row(cooldown_days=2.5),
        complete_row(max_bid="not-a-number"),
        complete_row(max_data_age_hours=0),
        complete_row(min_bid=4, max_bid=3),
    ],
)
def test_present_incomplete_or_malformed_rows_fail_closed(row):
    with pytest.raises(GuardrailConfigError):
        load_tenant_guard_config(Cursor(row), "tenant-1")
