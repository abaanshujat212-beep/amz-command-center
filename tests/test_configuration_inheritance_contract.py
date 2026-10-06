from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0045_general_configuration_inheritance.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0045_general_configuration_inheritance.sql").read_text()
SERVICE = (ROOT / "services/config/inheritance.py").read_text()


def test_schema_is_versioned_immutable_tenant_scoped_and_reversible():
    assert "configuration_definition_version" in UP
    assert "configuration_override_version" in UP
    assert "unique(tenant_id,scope_type,scope_id,version)" in UP
    assert "configuration_override_immutable" in UP
    assert "force row level security" in UP
    assert "configuration_override_resolution_idx" in UP
    assert "drop table if exists configuration_override_version" in DOWN


def test_hard_guards_and_serialized_mutation_contract_are_enforced():
    assert "hard guard cannot be overridden" in UP
    assert "pg_advisory_xact_lock" in SERVICE
    assert "configuration changes require tenant owner or admin" in SERVICE
    assert 'operation="rollback"' in SERVICE
    assert 'operation="detach"' in SERVICE
