"""Transactional retry and rollback lifecycle helpers."""

from __future__ import annotations

import datetime as dt

from services.actions import state_machine as sm
from services.actions.audit import EventType, append_event, event_for


def record_retry(conn, action: sm.Action, *, attempt: int, correlation_key: str, exhausted: bool = False) -> sm.Action:
    previous = action.status.value
    if exhausted:
        kind = EventType.RETRY_EXHAUSTED
        new_state = previous
    else:
        kind = EventType.RETRY_SCHEDULED
        action = sm.retry(action)
        new_state = action.status.value
        conn.execute(
            """update action set status=%s,error=null,approved_by=null,approved_at=null
                 where tenant_id=%s and id=%s""",
            (new_state, action.tenant_id, action.id),
        )
    append_event(
        conn,
        event_for(
            action,
            kind,
            correlation_key=correlation_key,
            dedupe_key=f"retry:{attempt}:{kind.value}",
            retry_attempt=attempt,
            previous_state=previous,
            new_state=new_state,
        ),
    )
    return action


def record_retry_attempt(conn, action: sm.Action, *, attempt: int, correlation_key: str) -> None:
    append_event(
        conn,
        event_for(
            action,
            EventType.RETRY_ATTEMPTED,
            correlation_key=correlation_key,
            dedupe_key=f"retry:{attempt}:attempted",
            retry_attempt=attempt,
            previous_state=action.status.value,
            new_state=action.status.value,
        ),
    )


def rollback_action(conn, action: sm.Action, client, *, now: dt.datetime, correlation_key: str, attempt: int = 1) -> sm.Action:
    append_event(
        conn,
        event_for(
            action,
            EventType.ROLLBACK_REQUESTED,
            correlation_key=correlation_key,
            dedupe_key=f"rollback:{attempt}:requested",
            retry_attempt=attempt,
            previous_state=action.status.value,
        ),
    )
    try:
        response = client.rollback(action)
        updated = sm.rollback(action, now=now, api_ok=True)
        classification = "success"
        kind = EventType.ROLLBACK_SUCCEEDED
    except Exception as exc:
        updated = sm.rollback(action, now=now, api_ok=False)
        response = None
        classification = "failed"
        kind = EventType.ROLLBACK_FAILED
        updated.error = str(exc)
    conn.execute(
        "update action set status=%s, rolled_back_at=%s, error=%s where tenant_id=%s and id=%s",
        (updated.status.value, updated.rolled_back_at, updated.error, updated.tenant_id, updated.id),
    )
    append_event(
        conn,
        event_for(
            updated,
            kind,
            correlation_key=correlation_key,
            dedupe_key=f"rollback:{attempt}:result",
            retry_attempt=attempt,
            previous_state=sm.Status.APPLIED.value,
            new_state=updated.status.value,
            applied_value=response,
            provider_result_classification=classification,
        ),
    )
    return updated
