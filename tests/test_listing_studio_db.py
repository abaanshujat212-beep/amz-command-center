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


def test_listing_versions_are_immutable_and_tenant_scoped():
    tenant_a, tenant_b, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(
            "insert into auth.auth_user(id,name,email) values(%s,'editor',%s)",
            (user_id, f"{user_id}@test"),
        )
        for tenant in (tenant_a, tenant_b):
            admin.execute(
                "insert into tenant(id,name,slug) values(%s,'listing',%s)", (tenant, str(tenant))
            )
            admin.execute(
                "insert into tenant_member(tenant_id,user_id,role) values(%s,%s,'owner')",
                (tenant, user_id),
            )
            admin.execute("select set_tenant(%s)", (tenant,))
            project = admin.execute(
                "insert into listing_project(tenant_id,name,created_by) values(%s,%s,%s) returning id",
                (tenant, f"listing-{tenant}", user_id),
            ).fetchone()[0]
            admin.execute(
                """insert into listing_draft_version(tenant_id,project_id,version,title,bullets,backend_terms,change_summary,created_by)
                values(%s,%s,1,'Original',%s,%s,'Initial sourced draft',%s)""",
                (tenant, project, Jsonb(["Fact-backed bullet"]), Jsonb(["term"]), user_id),
            )
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert app.execute("select count(*) from listing_project").fetchone()[0] == 1
                with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                    app.execute("update listing_draft_version set title='rewrite'")
                app.rollback()
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
            admin.execute("delete from auth.auth_user where id=%s", (user_id,))
