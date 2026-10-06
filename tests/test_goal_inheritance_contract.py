from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0044_ppc_goal_inheritance.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0044_ppc_goal_inheritance.sql").read_text()


def test_goal_schema_has_all_scopes_constraints_and_resolution_index():
    for scope in (
        "account",
        "portfolio",
        "product_family",
        "asin",
        "campaign",
        "ad_group",
        "target",
        "keyword",
    ):
        assert f"'{scope}'" in UP
    assert "exclude using gist" in UP
    assert "ppc_goal_override_resolution_idx" in UP
    assert "force row level security" in UP
    assert "audit_ppc_goal_override_created" in UP


def test_goal_schema_is_reversible():
    assert "drop table if exists ppc_goal_override_event" in DOWN
    assert "drop table if exists ppc_goal_override" in DOWN
