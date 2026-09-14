"""Durable action retry release and authorized dead-letter replay.

Failure classification and scheduling are performed by migration 0026 in the
same transaction as the worker's failed state update. This module claims due
rows safely and never performs an Amazon mutation itself.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import uuid
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from services.actions.audit import EventType, ExecutionEvent, append_event

APPROVER_ROLES = {"owner", "admin"}
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")


@dataclass(frozen=True)
class RetryRelease:
    action_id: str
    attempt: int


def _event(
    row: dict,
    event_type: EventType,
    *,
    actor_type: str,
    actor_id: str,
    correlation_key: str,
    dedupe_key: str,
) -> ExecutionEvent:
    return ExecutionEvent(
        tenant_id=str(row["tenant_id"]),
        action_id=str(row["id"]),
        event_type=event_type,
        correlation_key=correlation_key,
        idempotency_key=row["idempotency_key"],
        dedupe_key=dedupe_key,
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        actor_type=actor_type,
        actor_id=actor_id,
        previous_state="failed",
        new_state="pending",
        retry_attempt=int(row["retry_count"]),
        provider_result_classification=row.get("failure_classification"),
    )


def release_due_retries(
    conn,
    tenant_id: str,
    *,
    limit: int = 25,
    now: dt.datetime | None = None,
    correlation_key: str | None = None,
) -> list[RetryRelease]:
    """Claim due transient failures and return them to reviewable pending state."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    now = now or dt.datetime.now(dt.timezone.utc)
    correlation_key = correlation_key or f"retry-release:{uuid.uuid4()}"
    rows = conn.execute(
        """select id,tenant_id,entity_type,entity_id,idempotency_key,retry_count,
                  failure_classification
             from action
            where tenant_id=%s and status='failed' and dead_lettered_at is null
              and failure_classification='transient' and next_attempt_at <= %s
              and not exists (
                select 1 from action active
                 where active.tenant_id=action.tenant_id
                   and active.entity_type=action.entity_type
                   and active.entity_id=action.entity_id
                   and active.id<>action.id
                   and active.action_type<>'flag'
                   and active.status in ('pending','approved')
              )
            order by next_attempt_at,requested_at
            for update skip locked
            limit %s""",
        (tenant_id, now, limit),
    ).fetchall()
    released: list[RetryRelease] = []
    for row in rows:
        conn.execute(
            """update action set status='pending',next_attempt_at=null,
                      last_retry_at=%s,approved_by=null,approved_at=null
                 where tenant_id=%s and id=%s and status='failed'""",
            (now, tenant_id, row["id"]),
        )
        append_event(
            conn,
            _event(
                row,
                EventType.RETRY_ATTEMPTED,
                actor_type="system",
                actor_id="retry-worker",
                correlation_key=correlation_key,
                dedupe_key=f"retry:{row['retry_count']}:released",
            ),
        )
        released.append(RetryRelease(str(row["id"]), int(row["retry_count"])))
    return released


def replay_dead_letter(
    conn,
    *,
    tenant_id: str,
    action_id: str,
    actor_id: str,
    actor_role: str,
    correlation_key: str | None = None,
) -> RetryRelease:
    """Return one dead-lettered action to pending after an authorized decision."""
    if actor_role not in APPROVER_ROLES:
        raise PermissionError("only tenant owners and admins may replay dead letters")
    row = conn.execute(
        """select id,tenant_id,entity_type,entity_id,idempotency_key,retry_count,
                  failure_classification
             from action
            where tenant_id=%s and id=%s and status='failed'
              and dead_lettered_at is not null
            for update""",
        (tenant_id, action_id),
    ).fetchone()
    if row is None:
        raise LookupError("dead-lettered action not found for tenant")
    conn.execute(
        """update action set status='pending',next_attempt_at=null,
                  dead_lettered_at=null,dead_letter_reason=null,
                  replay_count=replay_count+1,approved_by=null,approved_at=null
             where tenant_id=%s and id=%s""",
        (tenant_id, action_id),
    )
    attempt = int(row["retry_count"])
    append_event(
        conn,
        _event(
            row,
            EventType.RETRY_SCHEDULED,
            actor_type="user",
            actor_id=actor_id,
            correlation_key=correlation_key or f"dead-letter-replay:{uuid.uuid4()}",
            dedupe_key=f"retry:{attempt}:replay:{actor_id}",
        ),
    )
    return RetryRelease(str(row["id"]), attempt)


def run_once(
    tenant_id: str,
    *,
    limit: int = 25,
    database_url: str = DATABASE_URL,
) -> list[RetryRelease]:
    """Release one bounded batch; transaction owns both states and audit events."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        released = release_due_retries(conn, tenant_id, limit=limit)
        conn.commit()
        return released


def main() -> None:
    parser = argparse.ArgumentParser(description="Release due action retries for review")
    parser.add_argument("--tenant-id", default=os.environ.get("DEV_TENANT_ID"))
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    if not args.tenant_id:
        raise SystemExit("--tenant-id or DEV_TENANT_ID is required")
    released = run_once(args.tenant_id, limit=args.limit)
    print(f"retry actions released={len(released)}")


if __name__ == "__main__":
    main()
