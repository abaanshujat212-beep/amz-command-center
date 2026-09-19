"""Canonical internal-event publisher for the existing in-app alert inbox."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field

from psycopg.types.json import Jsonb

from services.notifications.policy import evaluate_delivery_policy, load_preference

ALLOWED_EVENT_TYPES = frozenset({
    "auth_expiring", "auth_expired", "pipeline_failed", "data_stale",
    "blast_radius_halt", "budget_guard", "action_failed", "economics_incomplete",
    "low_inventory", "projected_stockout", "reorder_due", "inbound_delayed",
    "excess_stock", "unusual_demand",
})
ALLOWED_SOURCES = frozenset({"scheduler", "action_worker", "inventory_engine", "internal"})
ALLOWED_SEVERITIES = frozenset({"info", "warning", "critical"})
MAX_PAYLOAD_BYTES = 32_768


@dataclass(frozen=True)
class InternalEvent:
    tenant_id: str
    event_type: str
    source: str
    source_ref: str
    dedupe_key: str
    severity: str
    title: str
    payload: dict = field(default_factory=dict)
    occurred_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


@dataclass(frozen=True)
class PublishResult:
    event_id: str
    alert_id: str
    created: bool


def _validate(event: InternalEvent) -> None:
    if event.event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError("unsupported internal event type")
    if event.source not in ALLOWED_SOURCES:
        raise ValueError("unsupported internal event source")
    if event.severity not in ALLOWED_SEVERITIES:
        raise ValueError("unsupported notification severity")
    for name, value, limit in (("tenant_id", event.tenant_id, 128), ("source_ref", event.source_ref, 256),
                               ("dedupe_key", event.dedupe_key, 256), ("title", event.title, 512)):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"invalid {name}")
    if not isinstance(event.payload, dict):
        raise ValueError("notification payload must be an object")
    if len(json.dumps(event.payload, separators=(",", ":"), sort_keys=True).encode()) > MAX_PAYLOAD_BYTES:
        raise ValueError("notification payload is too large")
    if event.occurred_at.tzinfo is None or event.occurred_at.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")


def _cell(row, name: str, index: int = 0):
    return row[name] if isinstance(row, dict) else row[index]


def _wire_policy_decisions(conn, event: InternalEvent, event_id: str) -> None:
    """Persist policy outcomes; no provider or network call occurs."""
    for channel in ("in_app", "email", "whatsapp", "sms"):
        preference = load_preference(conn, event.tenant_id, event.event_type, channel)
        decision = evaluate_delivery_policy(
            preference, event.occurred_at, event.severity,
            has_consent=False, provider_configured=False,
            conn=conn, tenant_id=event.tenant_id,
            recipient_ref=None,
        )
        conn.execute(
            """update notification_delivery
                  set policy_decision=%s, eligible_at=%s, updated_at=now()
                where tenant_id=%s and event_id=%s and channel=%s""",
            (decision.status, decision.eligible_at, event.tenant_id, event_id, channel),
        )


def publish_in_app(conn, event: InternalEvent) -> PublishResult:
    """Publish once and apply canonical preference/consent policy."""
    _validate(event)
    detail = {"notification_source": event.source, "notification_source_ref": event.source_ref,
              "event_payload": event.payload}
    inserted = conn.execute(
        """insert into alert (tenant_id,kind,severity,title,detail,entity_ref,dedupe_key,created_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (tenant_id,dedupe_key) where dedupe_key is not null do nothing
           returning id::text""",
        (event.tenant_id, event.event_type, event.severity, event.title, Jsonb(detail),
         event.source_ref, event.dedupe_key, event.occurred_at),
    ).fetchone()
    created = inserted is not None
    row = conn.execute(
        "select id::text, notification_event_id::text from alert where tenant_id=%s and dedupe_key=%s",
        (event.tenant_id, event.dedupe_key),
    ).fetchone()
    if row is None or _cell(row, "notification_event_id", 1) is None:
        raise RuntimeError("notification event routing did not complete")
    event_id = str(_cell(row, "notification_event_id", 1))
    _wire_policy_decisions(conn, event, event_id)
    return PublishResult(event_id=event_id, alert_id=str(_cell(row, "id")), created=created)
