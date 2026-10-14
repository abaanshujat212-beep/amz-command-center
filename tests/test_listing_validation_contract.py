from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0058_listing_validation.sql").read_text(encoding="utf-8")
DOWN = (ROOT / "packages/db/migrations/down/0058_listing_validation.sql").read_text(encoding="utf-8")
WEB = (ROOT / "apps/web/lib/listings.ts").read_text(encoding="utf-8")
API = (ROOT / "apps/web/app/api/listings/projects/[id]/validate/route.ts").read_text(encoding="utf-8")
PAGE = (ROOT / "apps/web/app/listings/page.tsx").read_text(encoding="utf-8")


def test_generation_and_validation_records_are_tenant_scoped_and_reversible():
    for table in ("listing_generation_record", "listing_validation_run", "listing_validation_issue"):
        assert f"create table {table}" in UP
        assert f"drop table if exists {table}" in DOWN
    assert "force row level security" in UP
    assert "prompt_sha256" in UP
    assert "source_fact_ids jsonb" in UP
    assert "listing generation and validation records are immutable" in UP


def test_validation_contract_is_fail_closed_and_has_no_amazon_write_path():
    assert "ptd_contract_verified boolean not null default false" in UP
    assert "restrictions_status in ('unknown','clear','restricted','blocked','error')" in UP
    assert "sp_api" not in UP.lower()


def test_tenant_api_and_review_gate_use_latest_deterministic_validation():
    assert "withTenant(actor.tenantId" in API
    assert "validateLatestListingDraft" in API
    assert "draft must pass the latest deterministic validation before review" in WEB
    assert 'where tenant_id=$1 and draft_version_id=$2 order by created_at desc limit 1' in WEB
    assert "Validation is fail-closed" in PAGE
