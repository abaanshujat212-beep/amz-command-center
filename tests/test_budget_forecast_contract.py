from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = (ROOT / "packages/dbt/models/marts/mart_ppc_monthly_budget_forecast.sql").read_text()
SCHEMA = (ROOT / "packages/dbt/models/marts/schema.yml").read_text()
QUERY = (ROOT / "apps/web/lib/queries-budget-forecast.ts").read_text()
ROUTE = (ROOT / "apps/web/app/api/budget-forecast/route.ts").read_text()
PAGE = (ROOT / "apps/web/app/budget-forecast/page.tsx").read_text()


def test_forecast_uses_successful_ingest_coverage_and_settled_monthly_data():
    assert "dataset = 'ads_sp_campaign_daily'" in MODEL
    assert "r.status = 'success'" in MODEL
    assert "p.report_date between b.month_start and b.settled_through" in MODEL
    assert "local_today - settlement_lag_days" in MODEL
    assert "coalesce(d.spend, 0)" in MODEL
    assert "elapsed_days - covered_days" in MODEL
    assert "missing_days" in SCHEMA


def test_forecast_exposes_horizon_scenarios_confidence_and_limit_mismatch():
    for field in (
        "month_start", "month_end", "spend_forecast_low", "spend_forecast_base",
        "spend_forecast_high", "sales_forecast_low", "sales_forecast_high",
        "confidence_score", "PROJECTED_OVER_LIMIT", "CURRENCY_MISMATCH",
    ):
        assert field in MODEL
    assert "stddev_pop" in MODEL
    assert "NO_LIMIT_CONFIGURED" in SCHEMA


def test_api_and_page_reuse_existing_read_only_dry_run_blast_radius():
    assert 'withTenant(actor.tenantId' in ROUTE
    assert "configuration_simulation" in QUERY
    assert "configuration_rollout_event" in QUERY
    assert "affected_count" in QUERY
    assert "recentDryRunSummaries" in PAGE
    assert "No spend or sales values are written back to Amazon" in PAGE
