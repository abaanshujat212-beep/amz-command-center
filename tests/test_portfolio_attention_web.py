from pathlib import Path

ROOT = Path(__file__).parents[1]
ATTENTION = (ROOT / "apps/web/lib/portfolio-attention.ts").read_text()
PORTFOLIO = (ROOT / "apps/web/lib/portfolio.ts").read_text()
ROUTE = (ROOT / "apps/web/app/api/portfolio/summary/route.ts").read_text()


def test_attention_is_deterministic_and_deduplicated():
    assert "const priority" in ATTENTION
    assert "new Map<string, AttentionItem>()" in ATTENTION
    assert "tenantId}:${candidate.reason}" in ATTENTION
    assert "localeCompare" in ATTENTION
    assert "LLM" not in ATTENTION and "openai" not in ATTENTION.lower()


def test_attention_uses_canonical_signals_and_source_timestamps():
    for reason in (
        "DEAD_LETTER_ACTIONS",
        "FAILED_ACTIONS",
        "OPEN_ALERTS",
        "STALE_DATA",
        "NO_PERFORMANCE_DATA",
        "ACOS_ABOVE_TARGET",
        "PENDING_APPROVALS",
    ):
        assert reason in ATTENTION
    assert "signalObservedAt" in PORTFOLIO
    assert "target_acos_default" in PORTFOLIO
    assert "actual: number | null" in ATTENTION
    assert "threshold: number | null" in ATTENTION


def test_attention_routes_are_internal_and_inventory_is_not_invented():
    assert '"/history"' in ATTENTION
    assert '"/approvals"' in ATTENTION
    assert '"/campaigns"' in ATTENTION
    assert '"/alerts"' not in ATTENTION
    assert '"/actions?' not in ATTENTION
    assert "projected stockout" not in ATTENTION.lower()
    assert 'inventory: { state: "NO_DATA", value: null }' in PORTFOLIO


def test_attention_requires_independent_alert_entitlement():
    assert 'url.searchParams.get("includeAttention") === "true"' in ROUTE
    assert "portfolioSummary(session.session.token, workspaceId, page, pageSize, includeAttention)" in ROUTE
    assert "requireAlerts ? buildPortfolioAttention(accounts) : null" in PORTFOLIO
    assert "session_workspace_portfolio_tenants($1,$2,$3)" in PORTFOLIO
