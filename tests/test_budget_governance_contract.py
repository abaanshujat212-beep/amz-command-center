from pathlib import Path

ROOT=Path(__file__).parents[1]
UP=(ROOT/"packages/db/migrations/0062_portfolio_budget_governance.sql").read_text()
DOWN=(ROOT/"packages/db/migrations/down/0062_portfolio_budget_governance.sql").read_text()


def test_schema_is_versioned_audited_immutable_and_tenant_isolated():
    for fragment in ("version integer", "portfolio_budget_limit_event", "force row level security", "tenant_isolation", "before update or delete", "currency char(3)", "timezone text"):
        assert fragment in UP
    assert "drop table if exists portfolio_budget_limit" in DOWN


def test_guarded_api_ui_and_enforcement_are_wired():
    lib=(ROOT/"apps/web/lib/budget-governance.ts").read_text()
    page=(ROOT/"apps/web/app/settings/portfolio-budgets/page.tsx").read_text()
    route=(ROOT/"apps/web/app/api/portfolio-budgets/check/route.ts").read_text()
    assert "owner, admin or settings scope required" in lib
    assert "portfolio_budget_limit" in lib and "currency mismatch" in lib
    assert "withTenant" in route and "never write budgets to Amazon" in page
    assert "Europe/London" in page and "currency" in page
