"""Canonical internal-event publisher for the existing in-app alert inbox."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field

from psycopg.types.json import Jsonb

ALLOWED_EVENT_TYPES = frozenset(
    {
        "auth_expiring",
        "auth_expired",
        "pipeline_failed",
        "data_stale",
        "blast_radius_halt",
        "budget_guard",
        "action_failed",
        "economics_incomplete",
        "low_inventory",
        "projected_stockout",
        "reorder_due",
        "inbound_delayed",
        "excess_stock",
        "unusual_demand",
    }
)
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
    occurred_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc)
    )


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
    for name, value, limit in (
        ("tenant_id", event.tenant_id, 128),
        ("source_ref", event.source_ref, 256),
        ("dedupe_key", event.dedupe_key, 256),
        ("title", event.title, 512),
    ):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"invalid {name}")
    if not isinstance(event.payload, dict):
        raise ValueError("notification payload must be an object")
    encoded = json.dumps(event.payload, separators=(",", ":"), sort_keys=True).encode()
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ValueError("notification payload is too large")
    if event.occurred_at.tzinfo is None or event.occurred_at.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")


def _cell(row, name: str, index: int = 0):
    if isinstance(row, dict):
        return row[name]
    return row[index]


def publish_in_app(conn, event: InternalEvent) -> PublishResult:
    """Publish once and let the alert trigger record all channel outcomes.

    The caller owns the surrounding transaction. The alert row, immutable event,
    in-app delivery and blocked external-channel states therefore commit or roll
    back together.
    """
    _validate(event)
    detail = {
        "notification_source": event.source,
        "notification_source_ref": event.source_ref,
        "event_payload": event.payload,
    }
    inserted = conn.execute(
        """
        insert into alert (
          tenant_id,kind,severity,title,detail,entity_ref,dedupe_key,created_at
        ) values (%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (tenant_id,dedupe_key) where dedupe_key is not null do nothing
        returning id::text
        """,
        (
            event.tenant_id,
            event.event_type,
            event.severity,
            event.title,
            Jsonb(detail),
            event.source_ref,
            event.dedupe_key,
            event.occurred_at,
        ),
    ).fetchone()
    created = inserted is not None
    row = conn.execute(
        """
        select id::text, notification_event_id::text
          from alert
         where tenant_id=%s and dedupe_key=%s
        """,
        (event.tenant_id, event.dedupe_key),
    ).fetchone()
    if row is None or _cell(row, "notification_event_id", 1) is None:
        raise RuntimeError("notification event routing did not complete")
    return PublishResult(
        event_id=str(_cell(row, "notification_event_id", 1)),
        alert_id=str(_cell(row, "id")),
        created=created,
    )
