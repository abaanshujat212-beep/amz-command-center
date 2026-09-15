"""Canonical fail-closed loader for persisted tenant guardrails."""

from __future__ import annotations

from numbers import Real

from services.rules.guardrails import TenantGuardConfig

_FIELDS = (
    "automation_enabled",
    "dry_run",
    "max_change_pct",
    "cooldown_days",
    "max_changes_per_day",
    "max_budget_increase_per_day",
    "blast_radius_pct",
    "min_bid",
    "max_bid",
    "max_daily_budget",
    "max_data_age_hours",
    "settlement_lag_days",
)
_BOOL_FIELDS = ("automation_enabled", "dry_run")
_INT_FIELDS = (
    "cooldown_days",
    "max_changes_per_day",
    "max_data_age_hours",
    "settlement_lag_days",
)
_FLOAT_FIELDS = (
    "max_change_pct",
    "max_budget_increase_per_day",
    "blast_radius_pct",
    "min_bid",
    "max_bid",
    "max_daily_budget",
)


class GuardrailConfigError(RuntimeError):
    """Persisted settings exist but cannot safely authorize evaluation."""


def _validated_values(row: dict) -> dict:
    missing = [name for name in _FIELDS if name not in row or row[name] is None]
    if missing:
        raise GuardrailConfigError(
            "tenant guardrail settings are incomplete: " + ", ".join(missing)
        )

    values: dict = {}
    for name in _BOOL_FIELDS:
        if type(row[name]) is not bool:
            raise GuardrailConfigError(f"{name} must be boolean")
        values[name] = row[name]
    for name in _INT_FIELDS:
        if type(row[name]) is not int:
            raise GuardrailConfigError(f"{name} must be an integer")
        values[name] = row[name]
    for name in _FLOAT_FIELDS:
        value = row[name]
        if isinstance(value, bool) or not isinstance(value, Real):
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise GuardrailConfigError(f"{name} must be numeric") from exc
        values[name] = float(value)

    checks = (
        (0 < values["max_change_pct"] <= 1, "max_change_pct is outside (0, 1]"),
        (0 <= values["cooldown_days"] <= 90, "cooldown_days is outside [0, 90]"),
        (values["max_changes_per_day"] >= 0, "max_changes_per_day is negative"),
        (
            values["max_budget_increase_per_day"] >= 0,
            "max_budget_increase_per_day is negative",
        ),
        (0 < values["blast_radius_pct"] <= 1, "blast_radius_pct is outside (0, 1]"),
        (values["min_bid"] >= 0, "min_bid is negative"),
        (values["max_bid"] >= values["min_bid"], "max_bid is below min_bid"),
        (values["max_daily_budget"] >= 0, "max_daily_budget is negative"),
        (
            1 <= values["max_data_age_hours"] <= 720,
            "max_data_age_hours is outside [1, 720]",
        ),
        (
            0 <= values["settlement_lag_days"] <= 30,
            "settlement_lag_days is outside [0, 30]",
        ),
    )
    for valid, message in checks:
        if not valid:
            raise GuardrailConfigError(message)
    return values


def load_tenant_guard_config(cur, tenant_id: str) -> TenantGuardConfig:
    """Load one complete row; only row absence may use conservative defaults."""
    cur.execute(
        "select automation_enabled, dry_run, max_change_pct, cooldown_days,"
        " max_changes_per_day, max_budget_increase_per_day, blast_radius_pct,"
        " min_bid, max_bid, max_daily_budget, max_data_age_hours,"
        " settlement_lag_days from tenant_settings where tenant_id = %s",
        (tenant_id,),
    )
    row = cur.fetchone()
    if row is None:
        return TenantGuardConfig()
    return TenantGuardConfig(**_validated_values(row))
