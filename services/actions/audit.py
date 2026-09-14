"""Canonical append-only execution audit events."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import psycopg

_SECRET = re.compile(r"token|authorization|client.?secret|password|credential|cookie", re.I)


class EventType(StrEnum):
    APPLY_REQUESTED = "action.live_apply.requested"
    APPLY_STARTED = "action.live_apply.started"
    APPLY_SUCCEEDED = "action.live_apply.succeeded"
    APPLY_FAILED = "action.live_apply.failed"
    DRIFT_BLOCKED = "action.live_apply.drift_blocked"
    RETRY_SCHEDULED = "action.retry.scheduled"
    RETRY_ATTEMPTED = "action.retry.attempted"
    RETRY_EXHAUSTED = "action.retry.exhausted"
    ROLLBACK_REQUESTED = "action.rollback.requested"
    ROLLBACK_SUCCEEDED = "action.rollback.succeeded"
    ROLLBACK_FAILED = "action.rollback.failed"
    VERIFICATION_SCHEDULED = "action.verification.scheduled"
    VERIFICATION_CHECKPOINT = "action.verification.checkpoint"
    VERIFICATION_RESULT = "action.verification.result"
    VERIFICATION_TERMINAL = "action.verification.terminal"


@dataclass(frozen=True)
class ExecutionEvent:
    tenant_id: str
    action_id: str
    event_type: EventType
    correlation_key: str
    idempotency_key: str
    dedupe_key: str
    entity_type: str
    entity_id: str
    actor_type: str = "worker"
    actor_id: str | None = None
    marketplace_id: str = "A1F83G8C2ARO7P"
    account_scope: str | None = None
    previous_state: str | None = None
    new_state: str | None = None
    retry_attempt: int = 0
    rule_version: str | None = None
    engine_version: str | None = None
    policy_version: str | None = None
    before_value: Any = None
    proposed_value: Any = None
    applied_value: Any = None
    provider_result_classification: str | None = None
    verification_checkpoint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def sanitize(value: Any) -> Any:
    """Recursively redact credential-shaped fields and bound free-form strings."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SECRET.search(str(key)) else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return value[:1000]
    return value


def append_event(conn, event: ExecutionEvent) -> str | None:
    """Insert once per dedupe key; database transaction ownership stays with caller."""
    row = conn.execute(
        """
        insert into action_execution_event (
          tenant_id, marketplace_id, account_scope, action_id, actor_type, actor_id,
          event_type, previous_state, new_state, correlation_key, idempotency_key,
          dedupe_key, retry_attempt, rule_version, engine_version, policy_version,
          entity_type, entity_id, before_value, proposed_value, applied_value,
          provider_result_classification, verification_checkpoint, metadata)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s)
        on conflict (tenant_id, action_id, event_type, dedupe_key) do nothing
        returning id::text
        """,
        (
            event.tenant_id,
            event.marketplace_id,
            event.account_scope,
            event.action_id,
            event.actor_type,
            event.actor_id,
            event.event_type.value,
            event.previous_state,
            event.new_state,
            event.correlation_key,
            event.idempotency_key,
            event.dedupe_key,
            event.retry_attempt,
            event.rule_version,
            event.engine_version,
            event.policy_version,
            event.entity_type,
            event.entity_id,
            psycopg.types.json.Jsonb(sanitize(event.before_value)),
            psycopg.types.json.Jsonb(sanitize(event.proposed_value)),
            psycopg.types.json.Jsonb(sanitize(event.applied_value)),
            event.provider_result_classification,
            event.verification_checkpoint,
            psycopg.types.json.Jsonb(sanitize(event.metadata)),
        ),
    ).fetchone()
    return None if row is None else row[0]


def event_for(action, event_type: EventType, *, correlation_key: str, dedupe_key: str, **values) -> ExecutionEvent:
    return ExecutionEvent(
        tenant_id=action.tenant_id,
        action_id=action.id,
        event_type=event_type,
        correlation_key=correlation_key,
        idempotency_key=getattr(action, "idempotency_key", None) or action.id,
        dedupe_key=dedupe_key,
        entity_type=action.entity_type,
        entity_id=action.entity_id,
        before_value=action.before_value,
        proposed_value=action.after_value,
        **values,
    )
