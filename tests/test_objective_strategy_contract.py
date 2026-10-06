from pathlib import Path

from services.config.strategy_catalog import (
    OBJECTIVE_TEMPLATES,
    SAFE_GUARDRAILS,
    STRATEGY_TEMPLATES,
)

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0043_objective_strategy_schema.sql").read_text(
    encoding="utf-8"
)
DOWN = (ROOT / "packages/db/migrations/down/0043_objective_strategy_schema.sql").read_text(
    encoding="utf-8"
)
SEED = (ROOT / "packages/db/seed.py").read_text(encoding="utf-8")


def test_supported_modes_have_disabled_safe_templates():
    assert {row[1] for row in OBJECTIVE_TEMPLATES} == {
        "profitability",
        "growth",
        "efficiency",
        "launch",
        "defend",
    }
    assert {row[1] for row in STRATEGY_TEMPLATES} == {
        "conservative",
        "balanced",
        "growth",
        "harvest",
        "launch",
    }
    assert 0 < SAFE_GUARDRAILS["max_change_pct"] <= 0.10
    assert 0 < SAFE_GUARDRAILS["blast_radius_pct"] <= 0.10
    assert "false" in (ROOT / "services/config/strategy_catalog.py").read_text(encoding="utf-8")


def test_schema_is_immutable_audited_tenant_scoped_and_reversible():
    for table in (
        "objective_version",
        "strategy_version",
        "configuration_run_binding",
        "configuration_version_event",
    ):
        assert f"create table {table}" in UP
        assert f"drop table if exists {table}" in DOWN
    assert "configuration versions and bindings are immutable" in UP
    assert "audit_configuration_version_created" in UP
    assert "force row level security" in UP
    assert "validate_configuration_guardrails" in UP


def test_seed_is_idempotent_and_integrated():
    catalog = (ROOT / "services/config/strategy_catalog.py").read_text(encoding="utf-8")
    assert "on conflict(tenant_id,code,version) do nothing" in catalog
    assert "seed_templates(conn" in SEED
    assert "enabled,targets" in catalog and "false" in catalog
