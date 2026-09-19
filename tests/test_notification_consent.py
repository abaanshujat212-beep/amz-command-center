import datetime as dt

from services.notifications.consent import load_effective_consent
from services.notifications.policy import (
    BLOCKED_CONFIGURATION,
    BLOCKED_CONSENT,
    ELIGIBLE,
    RoutePreference,
    evaluate_delivery_policy,
)


class ConsentConnection:
    def __init__(self, value):
        self.value = value
        self.parameters = None

    def execute(self, _sql, parameters):
        self.parameters = parameters
        return self

    def fetchone(self):
        return {"consent": self.value}


NOW = dt.datetime(2026, 9, 19, 12, tzinfo=dt.timezone.utc)


def external(**overrides):
    values = {
        "event_type": "pipeline_failed",
        "channel": "email",
        "enabled": True,
    }
    values.update(overrides)
    return RoutePreference(**values)


def test_missing_recipient_or_invalid_scope_fails_closed():
    conn = ConsentConnection(True)
    assert load_effective_consent(conn, "tenant-1", None, "email") is False
    assert load_effective_consent(conn, "tenant-1", "recipient-1", "fax") is False
    assert conn.parameters is None


def test_policy_reads_canonical_effective_consent():
    conn = ConsentConnection(True)
    decision = evaluate_delivery_policy(
        external(), NOW, "warning", conn=conn, tenant_id="tenant-1", recipient_ref="recipient-1",
        provider_configured=True,
    )
    assert decision.status == ELIGIBLE
    assert conn.parameters == ("tenant-1", "recipient-1", "email", "operational_alert")


def test_revoked_or_missing_effective_consent_blocks_before_provider_gate():
    for consent in (False, None):
        decision = evaluate_delivery_policy(
            external(), NOW, "warning", conn=ConsentConnection(consent),
            tenant_id="tenant-1", recipient_ref="recipient-1", provider_configured=True,
        )
        assert decision.status == BLOCKED_CONSENT


def test_consent_does_not_make_provider_ready():
    decision = evaluate_delivery_policy(
        external(), NOW, "warning", conn=ConsentConnection(True),
        tenant_id="tenant-1", recipient_ref="recipient-1", provider_configured=False,
    )
    assert decision.status == BLOCKED_CONFIGURATION
