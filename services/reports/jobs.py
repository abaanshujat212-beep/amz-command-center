"""Tenant-scoped report definition and asynchronous job lifecycle.

Rendering, artifacts and delivery intentionally live in later layers. Every
function expects a transaction with the tenant already set through set_tenant.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Any

from psycopg.types.json import Jsonb

SUPPORTED_FORMATS = {"csv", "xlsx", "pdf"}


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class IdempotencyConflict(ValueError):
    """An idempotency key was reused with a different immutable scope."""


@dataclass(frozen=True)
class JobRef:
    id: str
    status: JobStatus
    attempt: int
    created: bool = False


def _event(
    conn,
    *,
    tenant_id: str,
    job_id: str,
    event_type: str,
    previous_state: str | None,
    new_state: str,
    attempt: int,
    actor_type: str,
    actor_id: str | None,
    dedupe_key: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """insert into report_job_event(
               tenant_id,report_job_id,event_type,previous_state,new_state,
               attempt,actor_type,actor_id,dedupe_key,metadata)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict(tenant_id,report_job_id,event_type,attempt,dedupe_key)
           do nothing""",
        (
            tenant_id,
            job_id,
            event_type,
            previous_state,
            new_state,
            attempt,
            actor_type,
            actor_id,
            dedupe_key,
            Jsonb(metadata or {}),
        ),
    )


def enqueue_job(
    conn,
    *,
    tenant_id: str,
    definition_code: str,
    definition_version: int,
    requested_by: str,
    idempotency_key: str,
    date_from: dt.date,
    date_to: dt.date,
    filters: dict[str, Any] | None,
    output_format: str,
    max_attempts: int = 3,
) -> JobRef:
    """Insert one immutable report request or return its exact idempotent match."""
    output_format = output_format.lower()
    if output_format not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported report format: {output_format}")
    if date_from > date_to:
        raise ValueError("date_from must not be after date_to")
    if not idempotency_key.strip():
        raise ValueError("idempotency_key is required")
    if not 1 <= max_attempts <= 10:
        raise ValueError("max_attempts must be between 1 and 10")
    filters = filters or {}
    definition = conn.execute(
        """select id,code,version,title,source_contract,
                  render_contract_version,definition
             from report_definition
            where tenant_id=%s and code=%s and version=%s and active=true""",
        (tenant_id, definition_code, definition_version),
    ).fetchone()
    if definition is None:
        raise LookupError("active report definition not found for tenant")
    snapshot = {
        "code": definition["code"],
        "version": definition["version"],
        "title": definition["title"],
        "source_contract": definition["source_contract"],
        "render_contract_version": definition["render_contract_version"],
        "definition": definition["definition"],
    }
    row = conn.execute(
        """insert into report_job(
               tenant_id,report_definition_id,definition_code,definition_version,
               definition_snapshot,requested_by,idempotency_key,date_from,date_to,
               filters,output_format,max_attempts)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict(tenant_id,idempotency_key) do nothing
           returning id,status,attempt""",
        (
            tenant_id,
            definition["id"],
            definition_code,
            definition_version,
            Jsonb(snapshot),
            requested_by,
            idempotency_key,
            date_from,
            date_to,
            Jsonb(filters),
            output_format,
            max_attempts,
        ),
    ).fetchone()
    if row is not None:
        _event(
            conn,
            tenant_id=tenant_id,
            job_id=str(row["id"]),
            event_type="report.queued",
            previous_state=None,
            new_state="queued",
            attempt=0,
            actor_type="user",
            actor_id=requested_by,
            dedupe_key="enqueue",
        )
        return JobRef(str(row["id"]), JobStatus(row["status"]), int(row["attempt"]), True)

    existing = conn.execute(
        """select id,status,attempt,definition_code,definition_version,
                  requested_by,date_from,date_to,filters,output_format,max_attempts
             from report_job where tenant_id=%s and idempotency_key=%s""",
        (tenant_id, idempotency_key),
    ).fetchone()
    expected = (
        definition_code,
        definition_version,
        str(requested_by),
        date_from,
        date_to,
        filters,
        output_format,
        max_attempts,
    )
    actual = (
        existing["definition_code"],
        int(existing["definition_version"]),
        str(existing["requested_by"]),
        existing["date_from"],
        existing["date_to"],
        existing["filters"],
        existing["output_format"],
        int(existing["max_attempts"]),
    )
    if actual != expected:
        raise IdempotencyConflict("idempotency key is already bound to another report scope")
    return JobRef(str(existing["id"]), JobStatus(existing["status"]), int(existing["attempt"]))


def claim_next_job(
    conn,
    *,
    tenant_id: str,
    worker_id: str,
    now: dt.datetime | None = None,
) -> JobRef | None:
    """Atomically claim one due job using the repository's skip-locked pattern."""
    now = now or dt.datetime.now(dt.timezone.utc)
    row = conn.execute(
        """select id,status,attempt from report_job
            where tenant_id=%s and status='queued' and next_attempt_at <= %s
            order by next_attempt_at,queued_at
            for update skip locked limit 1""",
        (tenant_id, now),
    ).fetchone()
    if row is None:
        return None
    updated = conn.execute(
        """update report_job
              set status='running',attempt=attempt+1,worker_id=%s,
                  started_at=%s,finished_at=null,error=null
            where tenant_id=%s and id=%s and status='queued'
            returning id,status,attempt""",
        (worker_id, now, tenant_id, row["id"]),
    ).fetchone()
    if updated is None:
        return None
    attempt = int(updated["attempt"])
    _event(
        conn,
        tenant_id=tenant_id,
        job_id=str(updated["id"]),
        event_type="report.started",
        previous_state="queued",
        new_state="running",
        attempt=attempt,
        actor_type="worker",
        actor_id=worker_id,
        dedupe_key=f"attempt:{attempt}:start",
    )
    return JobRef(str(updated["id"]), JobStatus.RUNNING, attempt)


def _finish(
    conn,
    *,
    tenant_id: str,
    job_id: str,
    worker_id: str,
    target: JobStatus,
    error: str | None,
    now: dt.datetime | None,
) -> JobRef:
    now = now or dt.datetime.now(dt.timezone.utc)
    row = conn.execute(
        """update report_job set status=%s,finished_at=%s,error=%s
            where tenant_id=%s and id=%s and status='running' and worker_id=%s
            returning id,status,attempt""",
        (target.value, now, error, tenant_id, job_id, worker_id),
    ).fetchone()
    if row is None:
        raise LookupError("running report job not found for worker and tenant")
    attempt = int(row["attempt"])
    _event(
        conn,
        tenant_id=tenant_id,
        job_id=job_id,
        event_type=f"report.{target.value}",
        previous_state="running",
        new_state=target.value,
        attempt=attempt,
        actor_type="worker",
        actor_id=worker_id,
        dedupe_key=f"attempt:{attempt}:{target.value}",
        metadata={"error": error} if error else None,
    )
    return JobRef(job_id, target, attempt)


def succeed_job(conn, *, tenant_id: str, job_id: str, worker_id: str) -> JobRef:
    return _finish(
        conn,
        tenant_id=tenant_id,
        job_id=job_id,
        worker_id=worker_id,
        target=JobStatus.SUCCEEDED,
        error=None,
        now=None,
    )


def fail_job(
    conn,
    *,
    tenant_id: str,
    job_id: str,
    worker_id: str,
    error: str,
) -> JobRef:
    if not error.strip():
        raise ValueError("report failure requires an error")
    return _finish(
        conn,
        tenant_id=tenant_id,
        job_id=job_id,
        worker_id=worker_id,
        target=JobStatus.FAILED,
        error=error,
        now=None,
    )


def retry_job(
    conn,
    *,
    tenant_id: str,
    job_id: str,
    actor_id: str,
    next_attempt_at: dt.datetime | None = None,
) -> JobRef:
    """Queue a failed job for a new bounded attempt without changing its scope."""
    next_attempt_at = next_attempt_at or dt.datetime.now(dt.timezone.utc)
    row = conn.execute(
        """update report_job
              set status='queued',queued_at=%s,next_attempt_at=%s,
                  started_at=null,finished_at=null,worker_id=null,error=null
            where tenant_id=%s and id=%s and status='failed'
              and attempt < max_attempts
            returning id,status,attempt""",
        (next_attempt_at, next_attempt_at, tenant_id, job_id),
    ).fetchone()
    if row is None:
        raise LookupError("retryable failed report job not found for tenant")
    attempt = int(row["attempt"])
    _event(
        conn,
        tenant_id=tenant_id,
        job_id=job_id,
        event_type="report.retry_queued",
        previous_state="failed",
        new_state="queued",
        attempt=attempt,
        actor_type="user",
        actor_id=actor_id,
        dedupe_key=f"attempt:{attempt}:retry",
    )
    return JobRef(job_id, JobStatus.QUEUED, attempt)
