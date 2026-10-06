import datetime as dt
import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get(
    "DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty"
)


def test_opportunity_feed_schedule_is_tenant_scoped_and_timezone_validated():
    tenant_a, tenant_b, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(
            "insert into auth.auth_user(id,name,email) values(%s,'feed owner',%s)",
            (user_id, f"{user_id}@test"),
        )
        for tenant in (tenant_a, tenant_b):
            admin.execute(
                "insert into tenant(id,name,slug) values(%s,'feed',%s)", (tenant, str(tenant))
            )
            admin.execute(
                "insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner')",
                (tenant, user_id),
            )
            admin.execute("select set_tenant(%s)", (tenant,))
            project = admin.execute(
                "insert into research_project(tenant_id,name,created_by) values(%s,%s,%s) returning id",
                (tenant, f"feed-{tenant}", user_id),
            ).fetchone()[0]
            admin.execute(
                """insert into opportunity_feed_schedule(
                       tenant_id,project_id,cadence,run_time,weekday,timezone,
                       next_run_at,created_by)
                   values(%s,%s,'weekly','09:00',1,'Europe/London',%s,%s)""",
                (tenant, project, dt.datetime(2026, 10, 6, 8, tzinfo=dt.timezone.utc), user_id),
            )
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert (
                    app.execute("select count(*) from opportunity_feed_schedule").fetchone()[0] == 1
                )
                app.rollback()
            with pytest.raises(psycopg.errors.InvalidParameterValue):
                admin.execute("select set_tenant(%s)", (tenant_a,))
                admin.execute(
                    "update opportunity_feed_schedule set timezone='Mars/Olympus' where tenant_id=%s",
                    (tenant_a,),
                )
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            admin.execute("delete from auth.auth_user where id=%s", (user_id,))
