"""Fail-closed reads of explicit notification provider readiness."""

from __future__ import annotations

ALLOWED_PROVIDER_CHANNELS = frozenset({"email", "whatsapp", "sms"})
READY = "READY"


def load_provider_ready(conn, tenant_id: str, channel: str) -> bool:
    if channel not in ALLOWED_PROVIDER_CHANNELS:
        return False
    row = conn.execute(
        """select readiness_state, evidence_expires_at
             from notification_provider_state
            where tenant_id=%s and channel=%s""",
        (tenant_id, channel),
    ).fetchone()
    if row is None:
        return False
    state = row["readiness_state"] if isinstance(row, dict) else row[0]
    expires_at = row["evidence_expires_at"] if isinstance(row, dict) else row[1]
    if state != READY:
        return False
    return expires_at is None or expires_at > __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
