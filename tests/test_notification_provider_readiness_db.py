import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from services.notifications.provider_readiness import load_provider_ready

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def _tenant(admin, name):
    tenant_id = uuid.uuid4()
    admin.execute("insert into tenant(id,name,slug) values(%s,%s,%s)", (tenant_id, name, f"{name}-{tenant_id}"))
    return tenant_id


def test_provider_state_is_tenant_scoped_audited_and_fail_closed_by_default():
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        tenant_a = _tenant(admin, "provider-a")
        tenant_b = _tenant(admin, "provider-b")
        try:
            admin.execute(
                """insert into notification_provider_state
                     (tenant_id,channel,config_ref,credential_ref,readiness_reason)
                     values(%s,'email','secret-manager://email-a','secret-ref-a','not verified'),
                           (%s,'email','secret-manager://email-b','secret-ref-b','not verified')""",
                (tenant_a, tenant_b),
            )
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert load_provider_ready(app, str(tenant_a), "email") is False
                assert app.execute("select count(*) as n from notification_provider_state").fetchone()["n"] == 1
                assert app.execute("select count(*) as n from notification_provider_state_audit").fetchone()["n"] == 1
                app.rollback()
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))


def test_ready_requires_verification_evidence_and_audit_is_append_only():
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        tenant_id = _tenant(admin, "provider-ready")
        try:
            with pytest.raises(psycopg.errors.CheckViolation):
                admin.execute(
                    """insert into notification_provider_state
                         (tenant_id,channel,readiness_state)
                         values(%s,'sms','READY')""", (tenant_id,),
                )
            row = admin.execute(
                """insert into notification_provider_state
                     (tenant_id,channel,readiness_state,verification_ref,evidence_observed_at)
                     values(%s,'sms','READY','verification-1',now()) returning id""", (tenant_id,),
            ).fetchone()
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (tenant_id,))
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute("delete from notification_provider_state_audit where provider_state_id=%s", (row[0],))
                app.rollback()
        finally:
            admin.execute("delete from tenant where id=%s", (tenant_id,))
