from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_completed_marts_have_discoverable_tenant_scoped_ui_queries():
    queries = (ROOT / "apps/web/lib/queries.ts").read_text(encoding="utf-8")
    layout = (ROOT / "apps/web/app/layout.tsx").read_text(encoding="utf-8")
    for mart, route in (
        ("mart_product_opportunity", "/opportunities"),
        ("mart_sqp_opportunity", "/sqp"),
        ("mart_sku_economics", "/economics"),
    ):
        assert f'mart("{mart}")' in queries
        assert route in layout
        assert (ROOT / f"apps/web/app{route}/page.tsx").is_file()


def test_dbt_schema_names_match_the_app_security_boundary():
    macro = (ROOT / "packages/dbt/macros/generate_schema_name.sql").read_text(encoding="utf-8")
    assert "custom_schema_name | trim" in macro
    assert "target.schema ~ '_'" not in macro


def test_dashboard_does_not_route_staging_models_through_mart_views():
    queries = (ROOT / "apps/web/lib/queries.ts").read_text(encoding="utf-8")
    assert 'mart("stg_' not in queries


def test_approval_ui_blocks_unverified_live_action_types():
    support = (ROOT / "apps/web/lib/action-support.ts").read_text(encoding="utf-8")
    actions = (ROOT / "apps/web/app/approvals/actions.ts").read_text(encoding="utf-8")
    page = (ROOT / "apps/web/app/approvals/page.tsx").read_text(encoding="utf-8")
    assert "LIVE_SUPPORTED" in support
    assert "liveActionSupport" in actions
    assert "!live.supported" in page
