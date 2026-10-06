from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0040_product_research_domain.sql").read_text(encoding="utf-8")
DOWN = (ROOT / "packages/db/migrations/down/0040_product_research_domain.sql").read_text(
    encoding="utf-8"
)
WEB = (ROOT / "apps/web/lib/research.ts").read_text(encoding="utf-8")
PAGE = (ROOT / "apps/web/app/research/page.tsx").read_text(encoding="utf-8")
NAV = (ROOT / "apps/web/lib/domain-navigation.ts").read_text(encoding="utf-8")


def test_research_schema_is_tenant_scoped_versioned_and_reversible():
    assert UP.startswith("-- 0040_product_research_domain.sql")
    for table in (
        "research_project",
        "research_candidate",
        "research_assumption",
        "research_observation",
    ):
        assert f"create table {table}" in UP
        assert "alter table %I force row level security" in UP
        assert f"drop table if exists {table}" in DOWN
    assert "unique (tenant_id, candidate_id, assumption_key, version)" in UP
    assert "research evidence and assumption versions are immutable" in UP


def test_external_values_require_complete_provenance():
    for field in (
        "provider text not null",
        "observed_at timestamptz not null",
        "method text not null",
        "evidence_scope jsonb not null",
        "completeness text not null",
        "evidence_ref text not null",
    ):
        assert field in UP
    assert "candidate_kind in ('own_catalog','market')" in UP
    assert "numeric_value is null" in UP and "text_value is null" in UP


def test_research_ui_and_api_queries_use_tenant_boundary():
    assert 'href: "/research"' in NAV
    assert "withTenant(actor.tenantId" in PAGE
    assert "where c.tenant_id=$1" in WEB
    assert "Market facts must include provider" in PAGE
    assert "fake opportunity rows" in PAGE
