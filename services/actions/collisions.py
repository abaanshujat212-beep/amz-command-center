"""Tenant-scoped pre-approval action collision detection.

This module records source-attributed manual/native evidence and reads the
canonical database collision function. Apply-time drift remains the final
protection in the worker; this service prevents known conflicts from reaching
approval.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from services.actions.audit import sanitize


class CollisionKind(str, Enum):
    ACTIVE_ACTION = "active_action"
    MANUAL_CHANGE = "manual_change"
    AMAZON_NATIVE_CHANGE = "amazon_native_change"
    RECENT_AXATY_CHANGE = "recent_axaty_change"


@dataclass(frozen=True)
class Collision:
    kind: CollisionKind
    conflicting_action_id: str | None
    change_signal_id: str | None
    evidence: dict[str, Any]


def detect(
    cur,
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    candidate_action_id: str | None = None,
    at: dt.datetime | None = None,
) -> Collision | None:
    """Return the highest-priority active collision visible to this tenant."""
    cur.execute(
        "select collision_kind, conflicting_action_id, change_signal_id, evidence "
        "from detect_action_collision(%s,%s,%s,%s,%s)",
        (tenant_id, entity_type, entity_id, candidate_action_id, at or dt.datetime.now(dt.timezone.utc)),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return Collision(
        kind=CollisionKind(row["collision_kind"]),
        conflicting_action_id=str(row["conflicting_action_id"]) if row["conflicting_action_id"] else None,
        change_signal_id=str(row["change_signal_id"]) if row["change_signal_id"] else None,
        evidence=dict(row["evidence"] or {}),
    )


def record_source_signal(
    cur,
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    source: str,
    change_kind: str,
    observed_at: dt.datetime,
    expires_at: dt.datetime,
    source_ref: str,
    marketplace_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> str:
    """Append idempotent, non-secret manual/native ownership evidence."""
    if source not in {"manual", "amazon_native"}:
        raise ValueError("source must be manual or amazon_native")
    if expires_at <= observed_at:
        raise ValueError("expires_at must be after observed_at")
    row = cur.execute(
        """insert into entity_change_signal
           (tenant_id,marketplace_id,entity_type,entity_id,source,change_kind,
            source_ref,observed_at,expires_at,evidence)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
           on conflict (tenant_id,source,source_ref) do nothing
           returning id""",
        (
            tenant_id,
            marketplace_id,
            entity_type,
            entity_id,
            source,
            change_kind,
            source_ref,
            observed_at,
            expires_at,
            json.dumps(sanitize(evidence or {})),
        ),
    ).fetchone()
    if row:
        return str(row[0] if not isinstance(row, dict) else row["id"])
    cur.execute(
        "select id from entity_change_signal where tenant_id=%s and source=%s and source_ref=%s",
        (tenant_id, source, source_ref),
    )
    existing = cur.fetchone()
    return str(existing[0] if not isinstance(existing, dict) else existing["id"])
