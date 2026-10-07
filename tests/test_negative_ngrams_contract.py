from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0048_search_term_ngram_recommendation.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0048_search_term_ngram_recommendation.sql").read_text()
MODULE = (ROOT / "services/rules/ngrams.py").read_text()


def test_findings_are_append_only_tenant_scoped_and_reversible():
    assert "force row level security" in UP
    assert "search_term_ngram_recommendation_immutable" in UP
    assert "references entity_protection(id, tenant_id)" in UP
    assert "grant select, insert on search_term_ngram_recommendation to axaty_app" in UP
    assert "drop table if exists search_term_ngram_recommendation" in DOWN


def test_auto_negative_cannot_carry_reasons_or_protection():
    assert "decision <> 'negative_phrase' or (cardinality(reasons) = 0" in UP
    assert "(decision = 'protected') = (protection_id is not null)" in UP


def test_analysis_never_reaches_amazon_and_respects_freshness():
    assert "resolve_source_freshness" in MODULE
    assert "insert into action" not in MODULE
    assert "services.actions" not in MODULE
