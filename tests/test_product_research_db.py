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


def test_research_rls_provenance_and_immutable_evidence():
    tenant_a, tenant_b, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(
            "insert into auth.auth_user(id,name,email) values(%s,'researcher',%s)",
            (user_id, f"{user_id}@test"),
        )
        for tenant in (tenant_a, tenant_b):
            admin.execute(
                "insert into tenant(id,name,slug) values(%s,'research',%s)",
                (tenant, str(tenant)),
            )
            admin.execute(
                "insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner')",
                (tenant, user_id),
            )
            admin.execute("select set_tenant(%s)", (tenant,))
            project = admin.execute(
                "insert into research_project(tenant_id,name,created_by) values(%s,%s,%s) returning id",
                (tenant, f"project-{tenant}", user_id),
            ).fetchone()[0]
            candidate = admin.execute(
                """insert into research_candidate(
                       tenant_id,project_id,candidate_kind,title,created_by)
                   values(%s,%s,'market','Attributed candidate',%s) returning id""",
                (tenant, project, user_id),
            ).fetchone()[0]
            admin.execute(
                """insert into research_observation(
                       tenant_id,candidate_id,metric,numeric_value,provider,observed_at,
                       method,evidence_scope,completeness,evidence_ref)
                   values(%s,%s,'price',19.99,'licensed-test',%s,'provider_api',%s,
                          'complete','fixture:price')""",
                (
                    tenant,
                    candidate,
                    dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc),
                    Jsonb({"marketplace": "UK"}),
                ),
            )
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert app.execute("select count(*) from research_candidate").fetchone()[0] == 1
                assert app.execute("select count(*) from research_observation").fetchone()[0] == 1
                with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                    app.execute("update research_observation set numeric_value=1")
                app.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                admin.execute("select set_tenant(%s)", (tenant_a,))
                admin.execute(
                    """insert into research_observation(
                           tenant_id,candidate_id,metric,numeric_value,text_value,provider,
                           observed_at,method,evidence_scope,completeness,evidence_ref)
                       select tenant_id,id,'invalid',1,'also text','test',now(),'manual',
                              '{}'::jsonb,'partial','invalid' from research_candidate
                        where tenant_id=%s limit 1""",
                    (tenant_a,),
                )
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            admin.execute("delete from auth.auth_user where id=%s", (user_id,))
