from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0042_listing_studio_foundation.sql").read_text(
    encoding="utf-8"
)
DOWN = (ROOT / "packages/db/migrations/down/0042_listing_studio_foundation.sql").read_text(
    encoding="utf-8"
)
WEB = (ROOT / "apps/web/lib/listings.ts").read_text(encoding="utf-8")
PAGE = (ROOT / "apps/web/app/listings/page.tsx").read_text(encoding="utf-8")
NAV = (ROOT / "apps/web/lib/domain-navigation.ts").read_text(encoding="utf-8")


def test_schema_is_versioned_tenant_scoped_and_reversible():
    for table in (
        "listing_project",
        "listing_product_fact",
        "listing_keyword_plan_version",
        "listing_draft_version",
        "listing_draft_fact",
        "listing_review_event",
    ):
        assert f"create table {table}" in UP
        assert f"drop table if exists {table}" in DOWN
    assert "force row level security" in UP
    assert "unique (tenant_id, project_id, version)" in UP
    assert "previous_version_id" in UP


def test_sources_ai_provenance_and_review_history_are_preserved():
    for field in (
        "source_type text not null",
        "source_ref text not null",
        "observed_at timestamptz not null",
        "product_fact_id uuid not null",
        "generation_ref text",
        "change_summary text not null",
    ):
        assert field in UP
    assert "listing versions and review events are immutable" in UP
    assert "only the latest draft" in WEB


def test_listing_workspace_is_discoverable_and_has_no_amazon_write_path():
    assert 'href: "/listings"' in NAV
    assert "where p.tenant_id=$1" in WEB
    assert "Amazon sync is disabled" in PAGE
    assert "writes to Amazon" in PAGE
    assert "sp_api" not in WEB.lower() and "ads_api" not in WEB.lower()
