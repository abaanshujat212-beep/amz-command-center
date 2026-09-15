"""Private report artifact persistence and renderer-worker integration."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from psycopg.types.json import Jsonb

from services.reports.jobs import JobRef, succeed_job
from services.reports.render import RenderedArtifact, render_dataset


class PrivateArtifactStore(Protocol):
    def put_private(
        self,
        *,
        tenant_id: str,
        job_id: str,
        content_sha256: str,
        media_type: str,
        data: bytes,
    ) -> str: ...


@dataclass(frozen=True)
class ArtifactRef:
    id: str
    job_id: str
    storage_key: str
    content_sha256: str
    media_type: str
    byte_size: int
    row_count: int
    expires_at: dt.datetime


def _persist(
    conn,
    *,
    tenant_id: str,
    job_id: str,
    rendered: RenderedArtifact,
    storage_key: str,
    created_at: dt.datetime,
    expires_at: dt.datetime,
) -> ArtifactRef:
    if not storage_key.strip() or "://" in storage_key:
        raise ValueError("artifact store must return an opaque private storage key, not a URL")
    row = conn.execute(
        """insert into report_artifact(
               tenant_id,report_job_id,output_format,media_type,file_extension,
               render_contract_version,storage_key,content_sha256,source_data_sha256,
               byte_size,row_count,reconciliation,created_at,expires_at)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           returning id,report_job_id,storage_key,content_sha256,media_type,
                     byte_size,row_count,expires_at""",
        (
            tenant_id,
            job_id,
            rendered.output_format,
            rendered.media_type,
            rendered.file_extension,
            rendered.contract_version,
            storage_key,
            rendered.content_sha256,
            rendered.source_data_sha256,
            len(rendered.data),
            rendered.row_count,
            Jsonb(rendered.reconciliation),
            created_at,
            expires_at,
        ),
    ).fetchone()
    return ArtifactRef(
        id=str(row["id"]),
        job_id=str(row["report_job_id"]),
        storage_key=row["storage_key"],
        content_sha256=row["content_sha256"],
        media_type=row["media_type"],
        byte_size=int(row["byte_size"]),
        row_count=int(row["row_count"]),
        expires_at=row["expires_at"],
    )


def render_claimed_job(
    conn,
    *,
    tenant_id: str,
    job_id: str,
    worker_id: str,
    columns: Iterable[str],
    rows: Iterable[Mapping[str, Any]],
    store: PrivateArtifactStore,
    retention_days: int = 30,
    now: dt.datetime | None = None,
) -> tuple[JobRef, ArtifactRef]:
    """Render, privately store, record and succeed a claimed job in one DB transaction."""
    if not 1 <= retention_days <= 3650:
        raise ValueError("retention_days must be between 1 and 3650")
    now = now or dt.datetime.now(dt.timezone.utc)
    job = conn.execute(
        """select id,output_format,definition_snapshot,attempt
             from report_job
            where tenant_id=%s and id=%s and status='running' and worker_id=%s
            for update""",
        (tenant_id, job_id, worker_id),
    ).fetchone()
    if job is None:
        raise LookupError("claimed report job not found for worker and tenant")
    contract_version = int(job["definition_snapshot"]["render_contract_version"])
    rendered = render_dataset(
        job["output_format"], columns, rows, contract_version=contract_version
    )
    storage_key = store.put_private(
        tenant_id=tenant_id,
        job_id=job_id,
        content_sha256=rendered.content_sha256,
        media_type=rendered.media_type,
        data=rendered.data,
    )
    artifact = _persist(
        conn,
        tenant_id=tenant_id,
        job_id=job_id,
        rendered=rendered,
        storage_key=storage_key,
        created_at=now,
        expires_at=now + dt.timedelta(days=retention_days),
    )
    completed = succeed_job(
        conn,
        tenant_id=tenant_id,
        job_id=job_id,
        worker_id=worker_id,
        metadata={
            "artifact_id": artifact.id,
            "content_sha256": artifact.content_sha256,
            "row_count": artifact.row_count,
        },
    )
    return completed, artifact


def get_available_artifact(
    conn,
    *,
    tenant_id: str,
    job_id: str,
    now: dt.datetime | None = None,
) -> ArtifactRef | None:
    """Recheck tenant scope and expiry before returning a private storage key."""
    now = now or dt.datetime.now(dt.timezone.utc)
    row = conn.execute(
        """select a.id,a.report_job_id,a.storage_key,a.content_sha256,a.media_type,
                  a.byte_size,a.row_count,a.expires_at
             from report_artifact a
             join report_job j on j.id=a.report_job_id and j.tenant_id=a.tenant_id
            where a.tenant_id=%s and a.report_job_id=%s
              and j.status='succeeded' and a.expires_at > %s""",
        (tenant_id, job_id, now),
    ).fetchone()
    if row is None:
        return None
    return ArtifactRef(
        id=str(row["id"]),
        job_id=str(row["report_job_id"]),
        storage_key=row["storage_key"],
        content_sha256=row["content_sha256"],
        media_type=row["media_type"],
        byte_size=int(row["byte_size"]),
        row_count=int(row["row_count"]),
        expires_at=row["expires_at"],
    )
