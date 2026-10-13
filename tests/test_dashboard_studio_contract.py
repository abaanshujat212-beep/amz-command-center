from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0054_dashboard_studio_contracts.sql").read_text()
DOWN = (ROOT / "packages/db/migrations/down/0054_dashboard_studio_contracts.sql").read_text()
LIB = (ROOT / "apps/web/lib/dashboard-studio.ts").read_text()
DB = (ROOT / "apps/web/lib/db.ts").read_text()


def test_dashboard_schema_is_versioned_tenant_scoped_and_reversible():
    for table in ("dashboard", "dashboard_version", "dashboard_default"):
        assert f"create table {table}" in UP
        assert f"alter table {table} force row level security" in UP
        assert f"drop table if exists {table}" in DOWN
    assert "unique(tenant_id,dashboard_id,version)" in UP
    assert "dashboard versions are immutable" in UP
    assert "current_dashboard_user()" in UP
    assert "visibility='team' or owner_user_id=current_dashboard_user()" in UP


def test_axaty_templates_are_independently_versioned_and_read_only_to_app():
    assert "primary key(template_key,version)" in UP
    assert "dashboard_template_version_immutable" in UP
    assert "revoke all on dashboard_template,dashboard_template_version from axaty_app" in UP
    assert "grant select on dashboard_template,dashboard_template_version to axaty_app" in UP
    assert "source_template_version" in UP


def test_widget_filter_and_query_contracts_are_allowlisted_twice():
    for value in ("scorecard", "table", "timeseries", "bar"):
        assert value in UP and value in LIB
    for value in ("dashboard.summary", "campaign.performance", "product.economics"):
        assert value in UP and value in LIB
    assert "dashboard_definition_valid(definition)" in UP
    assert "widget query is not allowlisted" in LIB
    assert "dashboard filter is not allowlisted" in LIB


def test_actor_scoped_helper_and_version_preserving_upgrade_exist():
    assert "withTenantActor" in DB
    assert "select set_dashboard_actor($1,$2)" in DB
    assert "The user's version remains untouched" in LIB
    assert '"dashboard.template_upgraded"' in LIB


def test_crud_duplicate_default_and_template_routes_exist():
    route_root = ROOT / "apps/web/app/api"
    expected = (
        "dashboards/route.ts",
        "dashboards/[id]/route.ts",
        "dashboards/[id]/duplicate/route.ts",
        "dashboards/[id]/default/route.ts",
        "dashboards/[id]/template/route.ts",
        "dashboard-templates/route.ts",
    )
    for relative in expected:
        source = (route_root / relative).read_text()
        assert "currentContext" in source
        assert "withTenantActor" in source
