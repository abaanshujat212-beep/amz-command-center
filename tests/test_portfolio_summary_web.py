from pathlib import Path

ROOT = Path(__file__).parents[1]
PORTFOLIO = (ROOT / "apps/web/lib/portfolio.ts").read_text()
ROUTE = (ROOT / "apps/web/app/api/portfolio/summary/route.ts").read_text()


def test_portfolio_authorizes_before_per_tenant_reads():
    assert "session_memberships($1)" in PORTFOLIO
    assert "session_workspace_tenant_authorization($1,$2,$3)" in PORTFOLIO
    assert "withTenant(membership.tenant_id" in PORTFOLIO
    assert "rowCount === 1" in PORTFOLIO
    assert "set row_security" not in PORTFOLIO.lower()


def test_unavailable_values_are_not_fabricated_as_zero():
    assert '"NO_DATA"' in PORTFOLIO
    assert "totals?.data_through ? totals.sales : null" in PORTFOLIO
    assert "totals?.data_through ? totals.cost : null" in PORTFOLIO
    assert 'inventory: { state: "NO_DATA", value: null }' in PORTFOLIO
    assert 'contributionProfit: { state: "NO_DATA", value: null }' in PORTFOLIO


def test_aggregates_keep_currency_boundaries_and_coverage():
    assert "aggregates.get(account.currency)" in PORTFOLIO
    assert "withPerformanceData" in PORTFOLIO
    assert "pageSize" in ROUTE and "Math.min(100" in ROUTE


def test_portfolio_route_requires_a_session_and_workspace():
    assert "auth.api.getSession" in ROUTE
    assert "A valid workspace ID is required" in ROUTE
    assert "No authorized accounts" in ROUTE
