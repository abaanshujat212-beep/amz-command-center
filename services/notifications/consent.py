"""Tenant-scoped consent reads for notification policy evaluation."""

from __future__ import annotations

ALLOWED_CONSENT_CHANNELS = frozenset({"email", "whatsapp", "sms"})
ALLOWED_CONSENT_PURPOSES = frozenset({"operational_alert"})


def load_effective_consent(
    conn,
    tenant_id: str,
    recipient_ref: str | None,
    channel: str,
    purpose: str = "operational_alert",
) -> bool:
    """Read canonical effective consent; missing identity or invalid scope fails closed."""
    if not recipient_ref or channel not in ALLOWED_CONSENT_CHANNELS:
        return False
    if purpose not in ALLOWED_CONSENT_PURPOSES:
        return False
    row = conn.execute(
        "select notification_consent_effective(%s,%s,%s,%s) as consent",
        (tenant_id, recipient_ref, channel, purpose),
    ).fetchone()
    if row is None:
        return False
    value = row["consent"] if isinstance(row, dict) else row[0]
    return value is True
