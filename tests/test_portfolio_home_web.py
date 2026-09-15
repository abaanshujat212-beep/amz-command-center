from pathlib import Path

ROOT = Path(__file__).parents[1]
PAGE = (ROOT / "apps/web/app/portfolio/page.tsx").read_text()
OPTIONS = (ROOT / "apps/web/app/api/context/options/route.ts").read_text()
SWITCHER = (ROOT / "apps/web/components/context-switcher.tsx").read_text()
OPEN = (ROOT / "apps/web/components/portfolio-open-account.tsx").read_text()
PORTFOLIO = (ROOT / "apps/web/lib/portfolio.ts").read_text()
ATTENTION = (ROOT / "apps/web/lib/portfolio-attention.ts").read_text()


def test_portfolio_entry_is_entitlement_backed_without_forcing_single_accounts():
    assert "can_view_portfolio" in OPTIONS
    assert "cross_account_summary_enabled" in OPTIONS
    assert "portfolioWorkspaces" in OPTIONS and "portfolioWorkspaces" in SWITCHER
    assert 'href={`/portfolio?workspaceId=' in SWITCHER
    assert "router.push(\"/portfolio\")" not in SWITCHER


def test_portfolio_page_uses_server_governed_summary():
    assert "session_workspaces($1)" in PAGE
    assert "portfolioSummary(session.session.token" in PAGE
    assert 'fetch("/api/portfolio/summary' not in PAGE
    assert "workspace.can_operate_tenants && <PortfolioOpenAccount" in PAGE
    assert "Portfolio access denied" in PAGE


def test_open_account_uses_canonical_revalidating_endpoint():
    assert 'fetch("/api/tenant/select"' in OPEN
    assert "JSON.stringify({ tenantId, workspaceId, returnTo })" in OPEN
    assert "router.push(result.returnTo)" in OPEN


def test_attention_first_filters_states_and_pagination_are_present():
    assert PAGE.index("Needs attention") < PAGE.index("Available aggregates")
    for state in ("NO_DATA", "STALE", "BLOCKED", "WAITING_FOR_AUTHORIZATION", "EXTERNAL_ACCESS_REQUIRED"):
        assert state in PAGE
    assert '<option>10</option><option>50</option><option>100</option>' in PAGE
    assert 'name="q"' in PAGE and 'name="state"' in PAGE and 'name="sort"' in PAGE
    assert "Portfolio pagination" in PAGE


def test_runtime_attention_routes_and_action_timestamp_query_are_valid():
    assert '"/alerts"' not in ATTENTION
    assert '"/actions?' not in ATTENTION
    assert '"/history"' in ATTENTION and '"/approvals"' in ATTENTION and '"/campaigns"' in ATTENTION
    assert "(max(requested_at) filter(where status='failed'))::text" in PORTFOLIO
    assert "max(requested_at)::text filter" not in PORTFOLIO
