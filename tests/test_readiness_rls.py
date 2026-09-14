import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def test_readiness_is_tenant_isolated_and_audited():
    a, b = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        for tenant_id, slug in ((a, "ready-a"), (b, "ready-b")):
            admin.execute("insert into tenant(id,name,slug) values(%s,%s,%s)", (tenant_id, slug, slug))
            admin.execute("insert into external_dependency_state(tenant_id,module_key,dependency_key) values(%s,'ads','authorization')", (tenant_id,))
    try:
        with psycopg.connect(APP_URL) as conn, conn.transaction():
            conn.execute("select set_tenant(%s)", (a,))
            assert conn.execute("select count(*) from external_dependency_state").fetchone()[0] == 1
            assert conn.execute("select count(*) from module_state").fetchone()[0] == 0
            assert conn.execute("select count(*) from audit_log where action='readiness.transition'").fetchone()[0] == 1
            with pytest.raises(psycopg.errors.Error):
                conn.execute("insert into module_state(tenant_id,module_key) values(%s,'inventory')", (b,))
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute("delete from tenant where id=any(%s)", ([a,b],))


def test_database_requires_evidence_for_live_ready():
    tenant_id = uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("insert into tenant(id,name,slug) values(%s,'ready-check',%s)", (tenant_id, str(tenant_id)))
        with pytest.raises(psycopg.errors.CheckViolation):
            admin.execute("insert into external_dependency_state(tenant_id,module_key,dependency_key,readiness_state) values(%s,'ads','auth','LIVE_READY')", (tenant_id,))
        admin.execute("delete from tenant where id=%s", (tenant_id,))
