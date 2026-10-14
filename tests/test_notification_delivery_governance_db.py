import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get(
    "DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty"
)


def test_templates_attempts_callbacks_and_cost_are_tenant_isolated():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            "insert into tenant(id,name,slug) values(%s,'notification-a',%s),(%s,'notification-b',%s)",
            (tenant_a, str(tenant_a), tenant_b, str(tenant_b)),
        )
        admin.commit()
        try:
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                template = app.execute(
                    """insert into notification_template(tenant_id,event_type,channel,status,subject_template,body_template,variable_allowlist,created_by,approved_by,approved_at) values(%s,'pipeline_failed','email','APPROVED','${title}','${summary}',array['title','summary'],gen_random_uuid(),gen_random_uuid(),now()) returning id""",
                    (tenant_a,),
                ).fetchone()
                alert = app.execute(
                    """insert into alert(tenant_id,kind,severity,title,detail,entity_ref,dedupe_key) values(%s,'pipeline_failed','warning','Pipeline failed','{}','pipeline','db-governance') returning id""",
                    (tenant_a,),
                ).fetchone()
                event = app.execute(
                    "select notification_event_id from alert where id=%s", (alert["id"],)
                ).fetchone()
                delivery = app.execute(
                    "update notification_delivery set template_id=%s,status='RETRYABLE',retry_eligible=true where tenant_id=%s and event_id=%s and channel='email' returning id",
                    (template["id"], tenant_a, event["notification_event_id"]),
                ).fetchone()
                app.execute(
                    """insert into notification_delivery_attempt(tenant_id,delivery_id,attempt_number,idempotency_key,outcome,error_code,cost_amount,cost_currency) values(%s,%s,1,'attempt-1','RETRYABLE','429',0.01,'GBP')""",
                    (tenant_a, delivery["id"]),
                )
                app.execute(
                    """insert into notification_callback_event(tenant_id,delivery_id,channel,provider_callback_id,delivery_status,signature_verified) values(%s,%s,'email','callback-1','DELIVERED',true)""",
                    (tenant_a, delivery["id"]),
                )
                assert (
                    app.execute("select count(*) n from notification_delivery_attempt").fetchone()[
                        "n"
                    ]
                    == 1
                )
                assert (
                    app.execute("select count(*) n from notification_callback_event").fetchone()[
                        "n"
                    ]
                    == 1
                )
                app.execute("select set_tenant(%s)", (tenant_b,))
                assert (
                    app.execute("select count(*) n from notification_template").fetchone()["n"] == 0
                )
                assert (
                    app.execute("select count(*) n from notification_delivery_attempt").fetchone()[
                        "n"
                    ]
                    == 0
                )
                assert (
                    app.execute("select count(*) n from notification_callback_event").fetchone()[
                        "n"
                    ]
                    == 0
                )
                app.rollback()
        finally:
            admin.execute("select set_tenant(%s)", (tenant_a,))
            admin.execute("delete from tenant where id in (%s,%s)", (tenant_a, tenant_b))
            admin.commit()


def test_delivery_evidence_is_immutable_and_unverified_callbacks_fail():
    tenant_id = uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            "insert into tenant(id,name,slug) values(%s,'notification-evidence',%s)",
            (tenant_id, str(tenant_id)),
        )
        admin.commit()
        try:
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_id,))
                alert = app.execute(
                    "insert into alert(tenant_id,kind,severity,title,detail,entity_ref,dedupe_key) values(%s,'data_stale','warning','Stale','{}','dataset','immutability') returning id",
                    (tenant_id,),
                ).fetchone()
                event = app.execute(
                    "select notification_event_id from alert where id=%s", (alert["id"],)
                ).fetchone()
                delivery = app.execute(
                    "select id from notification_delivery where event_id=%s and channel='email'",
                    (event["notification_event_id"],),
                ).fetchone()
                attempt = app.execute(
                    "insert into notification_delivery_attempt(tenant_id,delivery_id,attempt_number,idempotency_key,outcome) values(%s,%s,1,'immutable-1','FAILED') returning id",
                    (tenant_id, delivery["id"]),
                ).fetchone()
                with pytest.raises(psycopg.Error):
                    app.execute(
                        "update notification_delivery_attempt set error_code='changed' where id=%s",
                        (attempt["id"],),
                    )
                app.rollback()
                app.execute("select set_tenant(%s)", (tenant_id,))
                with pytest.raises(psycopg.Error):
                    app.execute(
                        "insert into notification_callback_event(tenant_id,delivery_id,channel,provider_callback_id,delivery_status,signature_verified) values(%s,%s,'email','bad','DELIVERED',false)",
                        (tenant_id, delivery["id"]),
                    )
                app.rollback()
        finally:
            admin.execute("select set_tenant(%s)", (tenant_id,))
            admin.execute("delete from tenant where id=%s", (tenant_id,))
            admin.commit()
