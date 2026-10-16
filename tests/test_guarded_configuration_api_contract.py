from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0059_guarded_configuration_api.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0059_guarded_configuration_api.sql").read_text()


def test_activation_and_replay_evidence_are_append_only_and_tenant_scoped():
    for table in ("configuration_activation_event", "configuration_write_request"):
        assert f"create table {table}" in UP
        assert f"alter table {table}" in UP or table in UP
    assert "force row level security" in UP
    assert "configuration_activation_immutable" in UP
    assert "configuration_request_immutable" in UP
    assert "unique (tenant_id,actor_user_id,idempotency_key)" in UP


def test_guarded_configuration_migration_is_reversible():
    assert "drop table if exists configuration_write_request" in DOWN
    assert "drop table if exists configuration_activation_event" in DOWN
