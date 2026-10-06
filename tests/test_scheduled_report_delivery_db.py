import datetime as dt
import os
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get(
    "DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty"
)


def test_report_schedule_is_tenant_scoped_and_validated():
    tenant_a, tenant_b, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(
            "insert into auth.auth_user(id,name,email) values(%s,'scheduler',%s)",
            (user_id, f"{user_id}@test"),
        )
        for tenant in (tenant_a, tenant_b):
            admin.execute(
                "insert into tenant(id,name,slug) values(%s,'schedule',%s)",
                (tenant, str(tenant)),
            )
            admin.execute(
                "insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner')",
                (tenant, user_id),
            )
            admin.execute("select set_tenant(%s)", (tenant,))
            definition = admin.execute(
                """insert into report_definition(
                       tenant_id,code,version,title,source_contract,definition,created_by)
                   values(%s,'scheduled',1,'Scheduled','scheduled-v1',%s,%s)
                   returning id""",
                (tenant, Jsonb({"columns": ["sales"]}), user_id),
            ).fetchone()[0]
            admin.execute(
                """insert into report_delivery_schedule(
                       tenant_id,report_definition_id,name,cadence,run_time,timezone,
                       recipient_user_id,channels,output_format,next_run_at,created_by)
                   values(%s,%s,'Daily summary','daily','09:00','Europe/London',
                          %s,array['in_app','email'],'pdf',%s,%s)""",
                (
                    tenant,
                    definition,
                    user_id,
                    dt.datetime(2026, 10, 6, 8, tzinfo=dt.timezone.utc),
                    user_id,
                ),
            )
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert (
                    app.execute("select count(*) from report_delivery_schedule").fetchone()[0] == 1
                )
                app.rollback()
            with pytest.raises(psycopg.errors.InvalidParameterValue):
                admin.execute("select set_tenant(%s)", (tenant_a,))
                admin.execute(
                    """update report_delivery_schedule set timezone='Mars/Olympus'
                        where tenant_id=%s""",
                    (tenant_a,),
                )
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            admin.execute("delete from auth.auth_user where id=%s", (user_id,))
