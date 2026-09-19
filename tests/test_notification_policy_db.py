import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from services.notifications.policy import load_preference

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get(
    "DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty"
)


def _tenant(admin, name):
    tenant_id = uuid.uuid4()
    admin.execute(
        "insert into tenant(id,name,slug) values(%s,%s,%s)",
        (tenant_id, name, f"{name}-{tenant_id}"),
    )
    return tenant_id


def test_preference_precedence_defaults_and_rls():
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        tenant_a = _tenant(admin, "notify-policy-a")
        tenant_b = _tenant(admin, "notify-policy-b")
        try:
            admin.execute(
                """insert into notification_route_preference
                     (tenant_id,event_type,channel,enabled,delivery_mode,
                      digest_interval_minutes,timezone)
                     values(%s,'*','email',true,'digest',1440,'UTC'),
                           (%s,'pipeline_failed','email',true,'immediate',null,'Asia/Karachi'),
                           (%s,'*','email',true,'immediate',null,'UTC')""",
                (tenant_a, tenant_a, tenant_b),
            )
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                specific = load_preference(
                    app, str(tenant_a), "pipeline_failed", "email"
                )
                assert specific.delivery_mode == "immediate"
                assert specific.timezone == "Asia/Karachi"
                wildcard = load_preference(app, str(tenant_a), "data_stale", "email")
                assert wildcard.delivery_mode == "digest"
                assert wildcard.digest_interval_minutes == 1440
                assert load_preference(
                    app, str(tenant_a), "data_stale", "sms"
                ).enabled is False
                assert app.execute(
                    "select count(*) as n from notification_route_preference"
                ).fetchone()["n"] == 2
                result = app.execute(
                    """update notification_route_preference set enabled=false
                         where tenant_id=%s""",
                    (tenant_b,),
                )
                assert result.rowcount == 0
                app.rollback()
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))


def test_database_rejects_invalid_timezone_and_in_app_disable():
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        tenant_id = _tenant(admin, "notify-policy-invalid")
        try:
            with pytest.raises(psycopg.errors.InvalidParameterValue):
                admin.execute(
                    """insert into notification_route_preference
                         (tenant_id,event_type,channel,enabled,timezone)
                         values(%s,'*','email',true,'Mars/Olympus')""",
                    (tenant_id,),
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                admin.execute(
                    """insert into notification_route_preference
                         (tenant_id,event_type,channel,enabled)
                         values(%s,'*','in_app',false)""",
                    (tenant_id,),
                )
        finally:
            admin.execute("delete from tenant where id=%s", (tenant_id,))
