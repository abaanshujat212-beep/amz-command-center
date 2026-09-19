import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from services.notifications.consent import load_effective_consent

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def _tenant(admin, name):
    tenant_id = uuid.uuid4()
    admin.execute("insert into tenant(id,name,slug) values(%s,%s,%s)", (tenant_id, name, f"{name}-{tenant_id}"))
    return tenant_id


def test_consent_history_and_effective_state_are_tenant_scoped():
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        tenant_a = _tenant(admin, "consent-a")
        tenant_b = _tenant(admin, "consent-b")
        try:
            admin.execute(
                """insert into notification_consent_event
                     (tenant_id,recipient_ref,channel,purpose,decision,occurred_at)
                     values(%s,'recipient-1','email','operational_alert','granted','2026-09-18T10:00:00Z'),
                           (%s,'recipient-1','email','operational_alert','revoked','2026-09-19T10:00:00Z'),
                           (%s,'recipient-1','email','operational_alert','granted','2026-09-20T10:00:00Z')""",
                (tenant_a, tenant_a, tenant_b),
            )
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert load_effective_consent(app, str(tenant_a), "recipient-1", "email") is False
                assert app.execute("select count(*) as n from notification_consent_event").fetchone()["n"] == 2
                app.execute("select set_tenant(%s)", (tenant_b,))
                assert load_effective_consent(app, str(tenant_b), "recipient-1", "email") is True
                app.rollback()
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([tenant_a, tenant_b],))


def test_consent_history_is_immutable_and_contact_data_is_not_consent():
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        tenant_id = _tenant(admin, "consent-immutable")
        try:
            row = admin.execute(
                """insert into notification_consent_event
                     (tenant_id,recipient_ref,channel,purpose,decision,occurred_at)
                     values(%s,'email-address','email','operational_alert','granted',now())
                     returning id""", (tenant_id,),
            ).fetchone()
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                admin.execute("update notification_consent_event set decision='revoked' where id=%s", (row[0],))
        finally:
            admin.execute("delete from tenant where id=%s", (tenant_id,))
