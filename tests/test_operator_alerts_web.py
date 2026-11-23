"""Source contracts for the canonical, tenant-scoped alert projection."""

from pathlib import Path

ROOT = Path(__file__).parents[1] / "apps/web"
SQL = (ROOT / "lib/operator-alerts.ts").read_text()
API = (ROOT / "app/api/alerts/route.ts").read_text()
PAGE = (ROOT / "app/alerts/page.tsx").read_text()
NAV = (ROOT / "lib/domain-navigation.ts").read_text()


def test_api_uses_only_the_authenticated_active_tenant():
    assert "await currentContext()" in API
    assert "loadOperatorAlerts(actor.tenantId, filters)" in API
    assert 'searchParams.get("tenantId")' not in API
    assert '"Cache-Control": "private, no-store"' in API
    assert "export async function POST" not in API


def test_sql_reads_only_open_allowlisted_alerts_in_the_existing_tenant_table():
    assert "withTenant(tenantId" in SQL
    assert "from alert a" in SQL
    assert "e.tenant_id = a.tenant_id" in SQL
    assert "a.tenant_id = $1" in SQL
    assert "a.resolved_at is null" in SQL
    assert "a.kind = any($2::text[])" in SQL
    assert "limit $4" in SQL
    for diagnostic_column in ("a.detail", "a.title", "a.entity_ref", "e.payload", "e.source_ref"):
        assert diagnostic_column not in SQL


def test_navigation_exposes_read_only_inbox_and_scope_is_explicit():
    assert '/alerts", label: "Operator alerts"' in NAV
    assert "tenant-wide, not limited to the selected account" in PAGE
    assert "currentTenantId()" in PAGE
    assert "aria-current" in PAGE
    assert "<time dateTime=" in PAGE
    assert "item.recovery.href" in PAGE
    assert "<form" not in PAGE
