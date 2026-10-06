from pathlib import Path

ROOT = Path(__file__).parents[1]
UP = (ROOT / "packages/db/migrations/0041_product_opportunity_feed.sql").read_text(encoding="utf-8")
DOWN = (ROOT / "packages/db/migrations/down/0041_product_opportunity_feed.sql").read_text(
    encoding="utf-8"
)
SERVICE = (ROOT / "services/research/opportunity_feed.py").read_text(encoding="utf-8")
WEB = (ROOT / "apps/web/lib/research.ts").read_text(encoding="utf-8")
PAGE = (ROOT / "apps/web/app/research/page.tsx").read_text(encoding="utf-8")


def test_feed_is_idempotent_tenant_scoped_and_reversible():
    assert UP.startswith("-- 0041_product_opportunity_feed.sql")
    assert "unique (tenant_id, schedule_id, scheduled_for)" in UP
    assert "uq_research_observation_id_tenant unique (id, tenant_id)" in UP
    assert "force row level security" in UP
    for table in ("opportunity_feed_item", "opportunity_feed_run", "opportunity_feed_schedule"):
        assert f"drop table if exists {table}" in DOWN


def test_ranking_requires_complete_attributed_score_evidence():
    assert "o.metric='opportunity_score'" in SERVICE
    assert "o.completeness='complete'" in SERVICE
    assert "o.numeric_value is not null" in SERVICE
    assert "No complete provider-attributed" in SERVICE
    assert "score_observation_id" in UP


def test_digest_reuses_canonical_router_and_is_opt_in():
    assert "publish_in_app" in SERVICE
    assert 'event_type="product_opportunity_digest"' in SERVICE
    assert 'if schedule["digest_enabled"]' in SERVICE
    assert "notification_event_id" in UP


def test_feed_is_visible_with_provenance_and_blocked_state():
    assert "where r.tenant_id=$1" in WEB
    for field in ("o.provider", "o.observed_at::text", "o.completeness"):
        assert field in WEB
    assert "blocked readiness" in PAGE
