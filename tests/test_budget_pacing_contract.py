from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERY = (ROOT / "apps/web/lib/queries-budget-pacing.ts").read_text()
PAGE = (ROOT / "apps/web/app/budget-pacing/page.tsx").read_text()
ROUTE = (ROOT / "apps/web/app/api/budget-pacing/route.ts").read_text()
NAV = (ROOT / "apps/web/lib/domain-navigation.ts").read_text()


def test_daily_pacing_uses_settled_tenant_mart_and_is_deterministic():
	assert 'mart("mart_ppc_budget_health_daily")' in QUERY
	assert "distinct on (campaign_id)" in QUERY
	assert "report_date >= current_date" in QUERY
	assert "spend / budget_amount < 0.8" in QUERY
	assert "spend / budget_amount > 1.2" in QUERY
	assert "settled_days_7d = 0 then 'unknown'" in QUERY


def test_api_and_ui_describe_read_only_daily_evidence_and_hourly_limit():
	assert "currentContext()" in ROUTE
	assert "actor.tenantId" in ROUTE
	assert "daily_settled_diagnostic" in ROUTE
	assert "hourly pacing remains unavailable until Marketing Stream data is connected" in PAGE
	assert "no budget changes are made" in PAGE
	assert 'href: "/budget-pacing"' in NAV
