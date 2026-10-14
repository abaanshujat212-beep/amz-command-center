from pathlib import Path

ROOT = Path(__file__).parents[1]
SQT = (ROOT / "packages/dbt/models/marts/mart_ppc_search_term_daily.sql").read_text()
SQP = (ROOT / "packages/dbt/models/marts/mart_sqp_opportunity.sql").read_text()
QUERIES = (ROOT / "apps/web/lib/queries.ts").read_text()
DRILLDOWN = (ROOT / "apps/web/lib/queries-drilldown.ts").read_text()
SEARCH_TERMS = (ROOT / "apps/web/app/search-terms/page.tsx").read_text()
SQP_PAGE = (ROOT / "apps/web/app/sqp/page.tsx").read_text()
TRENDS = (ROOT / "apps/web/app/search-trends/page.tsx").read_text()


def test_ads_and_sqp_observations_have_distinct_provenance_contracts():
    assert "'amazon_ads'::text as observation_source" in SQT
    assert "'owned_advertising'::text as observation_scope" in SQT
    assert "s.loaded_at as source_loaded_at" in SQT
    assert "'amazon_sqp'::text as observation_source" in SQP
    assert "'owned_product'::text as observation_scope" in SQP
    assert "max(loaded_at) as source_loaded_at" in SQP


def test_web_queries_carry_window_grain_and_source_freshness():
    for contract in (QUERIES, DRILLDOWN):
        for field in ("observation_source", "observation_scope", "observation_grain", "window_start", "window_end", "source_loaded_at"):
            assert field in contract


def test_ui_keeps_account_observations_separate_from_market_estimates():
    assert "Amazon Ads search-term report" in SEARCH_TERMS
    assert "Your advertised products only" in SEARCH_TERMS
    assert "your ASINs" in SQP_PAGE
    assert "not a market-wide trend estimate" in SQP_PAGE
    assert "External market source not configured" in TRENDS
    assert "does not infer them from PPC or SQP" in TRENDS
