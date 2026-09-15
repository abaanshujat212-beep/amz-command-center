import datetime as dt
import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.reports.artifacts import get_available_artifact, render_claimed_job
from services.reports.jobs import JobStatus, claim_next_job, enqueue_job

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


class MemoryStore:
    def __init__(self):
        self.values = {}

    def put_private(self, *, tenant_id, job_id, content_sha256, media_type, data):
        key = f"tenants/{tenant_id}/reports/{job_id}/{content_sha256}"
        self.values[key] = (media_type, data)
        return key


def _seed(admin, tenant_id, user_id):
    admin.execute("insert into tenant(id,name,slug) values(%s,'artifacts',%s)", (tenant_id, str(tenant_id)))
    admin.execute("insert into auth.auth_user(id,name,email) values(%s,'reporter',%s)", (user_id, f"{user_id}@test"))
    admin.execute("select set_tenant(%s)", (tenant_id,))
    admin.execute(
        """insert into report_definition(
               tenant_id,code,version,title,source_contract,definition,created_by)
           values(%s,'account',1,'Account','portfolio-summary-v1',%s,%s)""",
        (tenant_id, Jsonb({"columns": ["sku", "sales"]}), user_id),
    )
    admin.commit()


def test_renderer_records_private_reproducible_artifact_and_completion_event():
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        _seed(admin, tenant_id, user_id)
        try:
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_id,))
                job = enqueue_job(
                    app,
                    tenant_id=str(tenant_id),
                    definition_code="account",
                    definition_version=1,
                    requested_by=str(user_id),
                    idempotency_key="artifact-1",
                    date_from=dt.date(2026, 1, 1),
                    date_to=dt.date(2026, 1, 31),
                    filters={},
                    output_format="xlsx",
                )
                claim_next_job(app, tenant_id=str(tenant_id), worker_id="renderer-1")
                now = dt.datetime(2026, 2, 1, tzinfo=dt.timezone.utc)
                completed, artifact = render_claimed_job(
                    app,
                    tenant_id=str(tenant_id),
                    job_id=job.id,
                    worker_id="renderer-1",
                    columns=("sku", "sales"),
                    rows=({"sku": "A-1", "sales": 12.5},),
                    store=MemoryStore(),
                    retention_days=30,
                    now=now,
                )
                assert completed.status is JobStatus.SUCCEEDED
                assert artifact.storage_key.startswith(f"tenants/{tenant_id}/")
                assert "://" not in artifact.storage_key
                assert get_available_artifact(
                    app, tenant_id=str(tenant_id), job_id=job.id, now=now
                ) == artifact
                assert get_available_artifact(
                    app,
                    tenant_id=str(tenant_id),
                    job_id=job.id,
                    now=now + dt.timedelta(days=31),
                ) is None
                event = app.execute(
                    "select metadata from report_job_event where event_type='report.succeeded'"
                ).fetchone()
                assert event["metadata"]["content_sha256"] == artifact.content_sha256
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute("update report_artifact set storage_key='rewrite'")
                app.rollback()
        finally:
            admin.execute("select set_tenant(%s)", (tenant_id,))
            admin.execute("delete from report_job_event where tenant_id=%s", (tenant_id,))
            admin.execute("delete from report_artifact where tenant_id=%s", (tenant_id,))
            admin.execute("delete from report_job where tenant_id=%s", (tenant_id,))
            admin.execute("delete from report_definition where tenant_id=%s", (tenant_id,))
            admin.execute("delete from tenant where id=%s", (tenant_id,))
            admin.execute("delete from auth.auth_user where id=%s", (user_id,))
            admin.commit()


def test_artifact_rls_fails_closed_without_tenant_context():
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        _seed(admin, tenant_id, user_id)
        try:
            with psycopg.connect(APP_URL) as app:
                assert app.execute("select count(*) from report_artifact").fetchone()[0] == 0
        finally:
            admin.execute("select set_tenant(%s)", (tenant_id,))
            admin.execute("delete from report_definition where tenant_id=%s", (tenant_id,))
            admin.execute("delete from tenant where id=%s", (tenant_id,))
            admin.execute("delete from auth.auth_user where id=%s", (user_id,))
            admin.commit()
