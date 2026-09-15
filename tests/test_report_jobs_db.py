import datetime as dt
import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.reports.jobs import (
    IdempotencyConflict,
    JobStatus,
    claim_next_job,
    enqueue_job,
    fail_job,
    retry_job,
    succeed_job,
)

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def _seed(admin, tenant_id, user_id):
    admin.execute("insert into tenant(id,name,slug) values(%s,'reports',%s)", (tenant_id, str(tenant_id)))
    admin.execute("insert into auth.auth_user(id,name,email) values(%s,'reporter',%s)", (user_id, f"{user_id}@test"))
    admin.execute("select set_tenant(%s)", (tenant_id,))
    definition_id = admin.execute(
        """insert into report_definition(
               tenant_id,code,version,title,source_contract,definition,created_by)
           values(%s,'account-monthly',1,'Account monthly','portfolio-summary-v1',%s,%s)
           returning id""",
        (tenant_id, Jsonb({"columns": ["sales", "spend"]}), user_id),
    ).fetchone()[0]
    admin.commit()
    return definition_id


def test_report_job_lifecycle_idempotency_retry_and_events():
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        _seed(admin, tenant_id, user_id)
        try:
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_id,))
                kwargs = {
                    "tenant_id": str(tenant_id),
                    "definition_code": "account-monthly",
                    "definition_version": 1,
                    "requested_by": str(user_id),
                    "idempotency_key": "monthly-2026-01",
                    "date_from": dt.date(2026, 1, 1),
                    "date_to": dt.date(2026, 1, 31),
                    "filters": {"marketplace": "UK"},
                    "output_format": "csv",
                    "max_attempts": 2,
                }
                first = enqueue_job(app, **kwargs)
                second = enqueue_job(app, **kwargs)
                assert first.created is True and second.created is False
                assert first.id == second.id
                with pytest.raises(IdempotencyConflict):
                    enqueue_job(app, **{**kwargs, "date_to": dt.date(2026, 2, 1)})
                claimed = claim_next_job(app, tenant_id=str(tenant_id), worker_id="worker-1")
                assert claimed is not None and claimed.status is JobStatus.RUNNING
                fail_job(app, tenant_id=str(tenant_id), job_id=claimed.id, worker_id="worker-1", error="temporary render failure")
                retry_job(app, tenant_id=str(tenant_id), job_id=claimed.id, actor_id=str(user_id))
                second_claim = claim_next_job(app, tenant_id=str(tenant_id), worker_id="worker-2")
                assert second_claim is not None and second_claim.attempt == 2
                succeed_job(app, tenant_id=str(tenant_id), job_id=claimed.id, worker_id="worker-2")
                events = app.execute("select event_type from report_job_event order by occurred_at").fetchall()
                assert [row["event_type"] for row in events] == [
                    "report.queued",
                    "report.started",
                    "report.failed",
                    "report.retry_queued",
                    "report.started",
                    "report.succeeded",
                ]
                with pytest.raises(psycopg.errors.RaiseException, match="terminal"):
                    app.execute("update report_job set error='rewrite' where id=%s", (claimed.id,))
                app.rollback()
        finally:
            admin.execute("select set_tenant(%s)", (tenant_id,))
            admin.execute("delete from report_job_event where tenant_id=%s", (tenant_id,))
            admin.execute("delete from report_job where tenant_id=%s", (tenant_id,))
            admin.execute("delete from report_definition where tenant_id=%s", (tenant_id,))
            admin.execute("delete from tenant where id=%s", (tenant_id,))
            admin.execute("delete from auth.auth_user where id=%s", (user_id,))
            admin.commit()


def test_report_tables_fail_closed_and_isolate_tenants():
    tenant_a, tenant_b, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        _seed(admin, tenant_a, user_id)
        admin.execute("insert into tenant(id,name,slug) values(%s,'other',%s)", (tenant_b, str(tenant_b)))
        admin.commit()
        try:
            with psycopg.connect(APP_URL) as app:
                assert app.execute("select count(*) from report_definition").fetchone()[0] == 0
                app.execute("select set_tenant(%s)", (tenant_b,))
                assert app.execute("select count(*) from report_definition").fetchone()[0] == 0
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute("update report_job_event set metadata='{}'")
        finally:
            admin.execute("select set_tenant(%s)", (tenant_a,))
            admin.execute("delete from report_definition where tenant_id=%s", (tenant_a,))
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            admin.execute("delete from auth.auth_user where id=%s", (user_id,))
            admin.commit()
