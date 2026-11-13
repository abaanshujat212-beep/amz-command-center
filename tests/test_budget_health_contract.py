from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = (ROOT / "packages/dbt/models/marts/mart_ppc_budget_health_daily.sql").read_text()
SCHEMA = (ROOT / "packages/dbt/models/marts/schema.yml").read_text()
PAGE = (ROOT / "apps/web/app/budget-health/page.tsx").read_text()
QUERY = (ROOT / "apps/web/lib/queries-budget-health.ts").read_text()


def test_budget_health_uses_settled_rows_and_explicit_budget_thresholds():
    assert "where is_settled" in MODEL
    assert "between current_day.report_date - 6 and current_day.report_date" in MODEL
    assert "budget_utilisation > 1 then 'over_budget_delivery'" in MODEL
    assert "budget_utilisation >= 0.98 then 'capped'" in MODEL
    assert "budget_utilisation < 0.50 then 'underspend'" in MODEL
    assert "r.capped_days_7d >= 3 then 'high'" in MODEL
    assert "r.settled_days_7d < 5 then 'insufficient_data'" in MODEL


def test_profit_signals_require_complete_economics_and_preserve_unknowns():
    assert "bool_or(coalesce(history.economics_incomplete, true))" in MODEL
    assert "unknown_economics" in MODEL
    assert "profitable_dark" in MODEL
    assert "inefficient_consumer" in MODEL
    assert "over_budget_delivery" in SCHEMA
    assert "unknown_economics" in SCHEMA


def test_budget_health_page_reads_latest_rows_through_tenant_filtered_mart():
    assert 'withTenant(await currentTenantId()' in PAGE
    assert 'mart("mart_ppc_budget_health_daily")' in QUERY
    assert "where report_date >= current_date" in QUERY
    assert "never change budgets" in PAGE
