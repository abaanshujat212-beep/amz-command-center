from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0051_configuration_rollout.sql").read_text()
SERVICE = (ROOT / "services/config/simulation.py").read_text()


def test_storage_is_tenant_scoped_immutable_and_append_only():
    assert "force row level security" in UP and "configuration_simulation_immutable" in UP
    assert "configuration_rollout_event" in UP and "ROLLED_BACK" in UP


def test_simulator_has_no_action_or_provider_write_path():
    assert "insert into action" not in SERVICE and "AdsClient" not in SERVICE
    assert "aggregate exposure" in SERVICE and "protected" in SERVICE
