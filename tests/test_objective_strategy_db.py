import os
import uuid

import psycopg
import pytest

from services.config.strategy_catalog import seed_templates

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get(
    "DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty"
)


def test_templates_are_idempotent_immutable_validated_and_rls_scoped():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        for tenant in (tenant_a, tenant_b):
            admin.execute("select set_tenant(%s)", (tenant,))
            admin.execute(
                "insert into tenant(id,name,slug) values(%s,'config',%s)", (tenant, str(tenant))
            )
            assert seed_templates(admin, str(tenant)) == (5, 5)
            assert seed_templates(admin, str(tenant)) == (0, 0)
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert app.execute("select count(*) from objective_version").fetchone()[0] == 5
                assert (
                    app.execute("select bool_or(enabled) from objective_version").fetchone()[0]
                    is False
                )
                assert (
                    app.execute("select count(*) from configuration_version_event").fetchone()[0]
                    == 10
                )
                with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                    app.execute("update objective_version set enabled=true")
                app.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                admin.execute("select set_tenant(%s)", (tenant_a,))
                admin.execute(
                    """insert into objective_version(tenant_id,code,version,mode,name,targets,guardrails)
                    values(%s,'unsafe',1,'growth','Unsafe','{"target_acos":0.2}','{"unknown_guard":1}')""",
                    (tenant_a,),
                )
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))
