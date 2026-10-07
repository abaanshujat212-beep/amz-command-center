from pathlib import Path

ROOT = Path(__file__).parents[1]
NAME = "0049_search_term_lifecycle_recommendation.sql"
UP = (ROOT / "packages/db/migrations" / NAME).read_text()
DOWN = (ROOT / "packages/db/migrations/down" / NAME).read_text()
MODULE = (ROOT / "services/rules/isolation_revive.py").read_text()


def test_recommendations_are_append_only_tenant_scoped_and_reversible():
    assert "force row level security" in UP
    assert "search_term_lifecycle_recommendation_immutable" in UP
    assert "references search_term_harvest_lineage(id, tenant_id)" in UP
    assert "references entity_protection(id, tenant_id)" in UP
    assert "grant select, insert on search_term_lifecycle_recommendation to axaty_app" in UP
    assert "drop table if exists search_term_lifecycle_recommendation" in DOWN
    assert "drop constraint if exists search_term_harvest_lineage_id_tenant_key" in DOWN


def test_families_have_separate_shapes():
    assert "check ((decision = 'recommended') = (blocked_reason is null))" in UP
    assert "lineage_id is not null and match_type = 'negative_exact'" in UP
    assert "(decision = 'blocked') = (proposed_bid is null)" in UP
    assert "search_term_lifecycle_recommendation_one_isolation_idx" in UP


def test_analysis_never_reaches_amazon_and_respects_freshness():
    assert "resolve_source_freshness" in MODULE
    assert "insert into action" not in MODULE
    assert "services.actions" not in MODULE
