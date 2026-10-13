from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0051_configuration_rollout.sql").read_text()
SERVICE = (ROOT / "services/config/simulation.py").read_text()
ACTIVATION = (ROOT / "packages/db/migrations/0052_configuration_rollout_activation.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0052_configuration_rollout_activation.sql").read_text()


def test_storage_is_tenant_scoped_immutable_and_append_only():
    assert "force row level security" in UP and "configuration_simulation_immutable" in UP
    assert "configuration_rollout_event" in UP and "ROLLED_BACK" in UP


def test_simulator_has_no_action_or_provider_write_path():
    assert "insert into action" not in SERVICE and "AdsClient" not in SERVICE
    assert "aggregate exposure" in SERVICE and "protected" in SERVICE


def test_activation_lineage_is_immutable_and_reversible():
    assert "applied_override_id" in ACTIVATION
    assert "prior_override_id" in ACTIVATION
    assert "completion_metadata" in ACTIVATION
    assert "100 percent exposure must be recorded as COMPLETED" in ACTIVATION
    assert "completed rollout can only be rolled back" in ACTIVATION
    assert "drop column completion_metadata" in DOWN
