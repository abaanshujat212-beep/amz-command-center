from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "packages/db/migrations/0069_verification_confounding.sql").read_text()
QUERY = (ROOT / "apps/web/lib/queries-verification.ts").read_text()
PAGE = (ROOT / "apps/web/app/verification/page.tsx").read_text()


def test_confounding_evidence_is_additive_tenant_scoped_and_read_only():
    assert "security invoker" in MIGRATION
    assert "where s.tenant_id=p_tenant_id" in MIGRATION
    assert "other.tenant_id=f.tenant_id" in MIGRATION
    assert "signal.tenant_id=f.tenant_id" in MIGRATION
    assert "status='COMPLETE' then 'NO_RECORDED_CHANGES'" in MIGRATION
    assert "then 'CONFOUNDED'" in MIGRATION
    assert "update action_verification_snapshot" not in MIGRATION
    assert "verification_confounding_evidence(a.tenant_id,s.action_id,s.horizon_days)" in QUERY
    assert "a.tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid" in QUERY


def test_detection_uses_stored_half_open_utc_windows_and_historical_event_times():
    for column in (
        "window_before_start", "window_before_end", "window_after_start", "window_after_end",
    ):
        assert f"s.{column}::timestamp at time zone 'UTC'" in MIGRATION
    assert "other.applied_at>=f.before_start and other.applied_at<f.before_end" in MIGRATION
    assert "signal.observed_at>=f.after_start" in MIGRATION
    assert "signal.observed_at<f.after_end" in MIGRATION
    assert "other.rolled_back_at>=f.after_start" in MIGRATION
    assert "other.id<>f.id" in MIGRATION
    assert "limit 20" in MIGRATION
    assert "signal.expires_at" not in MIGRATION
    assert "No recorded overlap does not prove that no other factor changed." in PAGE
    assert "cannot be attributed to the verified action" in PAGE

