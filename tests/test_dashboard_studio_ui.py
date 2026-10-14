from pathlib import Path

ROOT = Path(__file__).parents[1]
PAGE = (ROOT / "apps/web/app/dashboard-studio/page.tsx").read_text(encoding="utf-8")
UI = (ROOT / "apps/web/components/dashboard-studio.tsx").read_text(encoding="utf-8")
DATA = (ROOT / "apps/web/lib/dashboard-studio-view.ts").read_text(encoding="utf-8")
NAV = (ROOT / "apps/web/lib/domain-navigation.ts").read_text(encoding="utf-8")


def test_studio_is_discoverable_and_uses_actor_scoped_saved_layouts():
    assert 'href: "/dashboard-studio"' in NAV
    assert "listDashboards" in PAGE
    assert "listDashboardTemplates" in PAGE
    assert "withTenantActor" in PAGE
    assert 'method: "PATCH"' in UI
    assert "Updated in Dashboard Studio" in UI


def test_catalog_and_execution_are_closed_allowlists_without_raw_sql_input():
    for query_key in (
        "dashboard.summary",
        "campaign.performance",
        "search_terms.performance",
        "product.economics",
        "sqp.opportunities",
        "pipeline.health",
    ):
        assert query_key in UI
        assert query_key in DATA
    assert "free-form SQL is never accepted" in UI
    assert "rawSql" not in UI
    assert "rawSql" not in DATA
    assert "eval(" not in UI


def test_templates_compare_filters_and_decision_overlays_are_present():
    for template in ("Executive", "PPC", "Profit", "Inventory readiness"):
        assert template in UI
    assert "Compare mode" in UI
    assert "Validated filters" in UI
    assert 'operator: "eq"' in UI
    assert "parseDashboardDefinition" in (
        ROOT / "apps/web/lib/dashboard-studio.ts"
    ).read_text(encoding="utf-8")
    assert "/copilot?action=" in UI
    assert "Decision evidence" in UI


def test_canvas_has_accessible_move_resize_tables_and_empty_states():
    for label in (
        "Move left",
        "Move right",
        "Move up",
        "Move down",
        "Make wider",
        "Make narrower",
        "Make taller",
        "Make shorter",
    ):
        assert label in UI
    assert "aria-label={`${selected.name} dashboard canvas`}" in UI
    assert '<caption className="sr-only">' in UI
    assert "No persisted rows match this widget and its filters." in UI
    assert "grid-cols-1" in UI and "md:grid-cols-12" in UI


def test_widget_data_is_tenant_transaction_data_and_overlays_are_stored_evidence():
    assert "loadStudioData(client" in PAGE
    assert "from action order by requested_at desc" in DATA
    assert "recentPipelineRuns" in DATA
    assert "searchTermPerformance" in DATA
    assert "sqpOpportunities" in DATA
