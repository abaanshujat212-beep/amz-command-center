from pathlib import Path

ROOT = Path(__file__).parents[1]
PAGE = (ROOT / "apps/web/app/settings/notifications/page.tsx").read_text()
ACTIONS = (ROOT / "apps/web/app/settings/notifications/actions.ts").read_text()
QUERIES = (ROOT / "apps/web/lib/notifications.ts").read_text()


def test_notification_settings_exposes_governed_routes_templates_and_delivery_evidence():
    for phrase in (
        "Quiet",
        "Digest",
        "Approved message templates",
        "Delivery audit, retries and cost",
        "Dead letter",
    ):
        assert phrase in PAGE
    assert "notification_delivery_attempt" not in PAGE
    assert "withTenant(actor.tenantId" in PAGE
    assert "currentContext()" in PAGE


def test_settings_mutations_reauthorize_and_write_audit_log():
    assert ACTIONS.count("permitted(actor.role)") == 2
    assert "notification.route_saved" in ACTIONS
    assert "notification.template_saved" in ACTIONS
    assert "process.env" not in ACTIONS
    assert "notification_delivery d" in QUERIES
    assert "e.tenant_id=d.tenant_id" in QUERIES
