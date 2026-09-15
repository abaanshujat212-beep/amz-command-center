from pathlib import Path

ROOT = Path(__file__).parents[1]
REPORTS = (ROOT / "apps/web/lib/reports.ts").read_text()
ROUTES = [
    ROOT / "apps/web/app/api/reports/route.ts",
    ROOT / "apps/web/app/api/reports/[id]/route.ts",
    ROOT / "apps/web/app/api/reports/[id]/retry/route.ts",
    ROOT / "apps/web/app/api/reports/[id]/download/route.ts",
]
PAGE = (ROOT / "apps/web/app/reports/page.tsx").read_text()
NAV = (ROOT / "apps/web/lib/domain-navigation.ts").read_text()


def test_report_routes_reauthorize_and_use_tenant_transactions():
    for route in ROUTES:
        source = route.read_text()
        assert "currentContext" in source
        assert "withTenant" in source
    assert "a.tenant_id=$1" in REPORTS
    assert "j.status='succeeded'" in REPORTS
    assert "a.expires_at>now()" in REPORTS


def test_report_mutations_are_role_guarded_and_viewers_remain_read_only():
    assert 'REQUEST_ROLES = new Set<TenantRole>(["owner", "admin", "user", "analyst"])' in REPORTS
    assert "cannot request reports" in REPORTS
    assert "cannot retry reports" in REPORTS
    assert "Read-only" in PAGE


def test_download_is_private_expiry_aware_and_integrity_checked():
    download = ROUTES[-1].read_text()
    assert "storage_key" not in download
    assert '"Cache-Control": "private, no-store"' in download
    assert "createHash(\"sha256\")" in REPORTS
    assert "REPORT_ARTIFACT_ROOT" in REPORTS
    assert "artifact failed integrity verification" in REPORTS


def test_reports_workspace_preserves_explicit_states_and_no_delivery():
    for state in ("AVAILABLE", "EXPIRED", "UNAVAILABLE", "FAILED", "PENDING"):
        assert state in REPORTS
    assert "reconciliation" in PAGE
    assert "Scheduled and external delivery are not enabled" in PAGE
    assert '{ href: "/reports", label: "Reports" }' in NAV
    assert not (ROOT / "packages/db/migrations/0034_reports_workspace.sql").exists()
