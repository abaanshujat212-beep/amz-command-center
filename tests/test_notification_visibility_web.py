"""Static safety contract for tenant-scoped notification visibility."""
from pathlib import Path

ROOT = Path(__file__).parents[1]
NOTIFICATIONS = (ROOT / "apps/web/lib/notifications.ts").read_text()
HISTORY = (ROOT / "apps/web/app/history/page.tsx").read_text()
SETTINGS = (ROOT / "apps/web/app/settings/notifications/page.tsx").read_text()
NAV = (ROOT / "apps/web/components/settings-nav.tsx").read_text()


def test_history_reuses_alert_inbox_with_canonical_delivery_metadata():
    assert "from alert a" in NOTIFICATIONS
    assert "notification_event e" in NOTIFICATIONS
    assert "notification_delivery d" in NOTIFICATIONS
    assert "d.channel = 'in_app'" in NOTIFICATIONS
    assert "notificationAlerts(c, 10)" in HISTORY
    assert "legacy alert · not routed" in HISTORY


def test_delivery_visibility_stays_tenant_scoped_and_server_side():
    assert "currentTenantId()" in SETTINGS
    assert "withTenant(tenantId, notificationDeliverySummary)" in SETTINGS
    assert "from notification_delivery" in NOTIFICATIONS
    assert "fetch(" not in SETTINGS


def test_external_channels_are_truthfully_blocked_and_read_only():
    for channel in ("Email", "WhatsApp", "SMS"):
        assert channel in SETTINGS
    assert "Blocked configuration" in SETTINGS
    assert "External delivery is not enabled" in SETTINGS
    assert "Provider credentials alone do not make a channel ready" in SETTINGS
    assert "This page is read-only" in SETTINGS
    assert "process.env" not in SETTINGS
    assert "<form" not in SETTINGS


def test_settings_navigation_exposes_notification_audit():
    assert '["/settings/notifications", "Notifications"]' in NAV
