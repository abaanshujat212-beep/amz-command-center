"""Static safety contract for the R07.4 isolation/revive recommendations UI."""
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEB = ROOT / "apps/web"
QUERIES = (WEB / "lib/queries-lifecycle.ts").read_text()
PAGE = (WEB / "app/term-lifecycle/page.tsx").read_text()
ROUTE = (WEB / "app/api/term-lifecycle/route.ts").read_text()
NAV = (WEB / "lib/domain-navigation.ts").read_text()


def test_lifecycle_ui_is_read_only_and_tenant_scoped():
    for source in (PAGE, ROUTE):
        assert "withTenant(tenantId" in source
        assert "export async function POST" not in source
    for source in (QUERIES, PAGE, ROUTE):
        lowered = source.lower()
        for verb in ("insert into", "update ", "delete from"):
            assert verb not in lowered
        assert "set_tenant" not in source
    assert "from search_term_lifecycle_recommendation" in QUERIES
    assert "marts." not in QUERIES


def test_both_families_and_every_block_reason_are_explained():
    for family in ("isolation_negative", "revive_target"):
        assert family in QUERIES and family in PAGE
    up = (ROOT / "packages/db/migrations/0049_search_term_lifecycle_recommendation.sql").read_text()
    reasons = up.split("blocked_reason text check (blocked_reason in (")[1].split("))")[0]
    for reason in (r.strip().strip("'") for r in reasons.split(",")):
        assert f"{reason}:" in PAGE, reason
    assert "Recommendations only." in PAGE


def test_page_is_reachable_from_ads_navigation():
    assert '{ href: "/term-lifecycle", label: "Isolation & revive" }' in NAV
