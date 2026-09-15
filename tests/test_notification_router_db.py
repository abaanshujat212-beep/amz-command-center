import datetime as dt
import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.notifications.router import InternalEvent, publish_in_app

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def _seed(admin, tenant_id):
    admin.execute(
        "insert into tenant(id,name,slug) values(%s,'notifications',%s)",
        (tenant_id, str(tenant_id)),
    )
    admin.commit()


def _cleanup(admin, tenant_id):
    admin.execute("select set_tenant(%s)", (tenant_id,))
    admin.execute("delete from tenant where id=%s", (tenant_id,))
    admin.commit()


def test_internal_event_is_idempotent_and_routes_only_in_app():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        _seed(admin, tenant_a)
        _seed(admin, tenant_b)
        try:
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_a,))
                event = InternalEvent(
                    tenant_id=str(tenant_a),
                    event_type="pipeline_failed",
                    source="scheduler",
                    source_ref="sales_traffic_asin_daily",
                    dedupe_key="pipeline:failure:2026-09-15",
                    severity="critical",
                    title="Sales pipeline failed",
                    payload={"dataset": "sales_traffic_asin_daily", "error": "boom"},
                    occurred_at=dt.datetime(2026, 9, 15, tzinfo=dt.timezone.utc),
                )
                first = publish_in_app(app, event)
                second = publish_in_app(app, event)
                assert first.created is True
                assert second.created is False
                assert first.event_id == second.event_id
                assert first.alert_id == second.alert_id
                assert app.execute("select count(*) from alert").fetchone()[0] == 1
                assert app.execute("select count(*) from notification_event").fetchone()[0] == 1
                deliveries = app.execute(
                    """select channel,status,attempt,retry_eligible,cost_amount,alert_id,error
                         from notification_delivery order by channel"""
                ).fetchall()
                assert len(deliveries) == 4
                in_app = next(row for row in deliveries if row["channel"] == "in_app")
                assert in_app["status"] == "DELIVERED"
                assert in_app["attempt"] == 1
                assert in_app["alert_id"] is not None
                assert in_app["cost_amount"] == 0
                for row in deliveries:
                    if row["channel"] != "in_app":
                        assert row["status"] == "BLOCKED_CONFIGURATION"
                        assert row["attempt"] == 0
                        assert row["retry_eligible"] is False
                        assert row["alert_id"] is None
                        assert row["cost_amount"] == 0
                        assert row["error"] == "channel is not configured"
                app.commit()

                app.execute("select set_tenant(%s)", (tenant_b,))
                assert app.execute("select count(*) from notification_event").fetchone()[0] == 0
                assert app.execute("select count(*) from notification_delivery").fetchone()[0] == 0
                assert app.execute("select count(*) from alert").fetchone()[0] == 0
                app.rollback()
        finally:
            _cleanup(admin, tenant_a)
            _cleanup(admin, tenant_b)


def test_existing_scheduler_alert_is_canonicalized_transactionally():
    tenant_id = uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        _seed(admin, tenant_id)
        try:
            with psycopg.connect(APP_URL, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_id,))
                alert = app.execute(
                    """insert into alert(tenant_id,kind,severity,title,detail,entity_ref)
                         values(%s,'data_stale','warning','dataset is stale',%s,'ads_sp_campaign_daily')
                         returning id""",
                    (tenant_id, Jsonb({"dataset": "ads_sp_campaign_daily", "scheduler_kind": "stale"})),
                ).fetchone()
                event = app.execute(
                    """select e.source,e.source_ref,e.event_type,e.payload
                         from notification_event e join alert a on a.notification_event_id=e.id
                        where a.id=%s""",
                    (alert["id"],),
                ).fetchone()
                assert event["source"] == "scheduler"
                assert event["source_ref"] == "ads_sp_campaign_daily"
                assert event["event_type"] == "data_stale"
                assert event["payload"]["scheduler_kind"] == "stale"
                states = {
                    row["channel"]: row["status"]
                    for row in app.execute(
                        "select channel,status from notification_delivery"
                    ).fetchall()
                }
                assert states == {
                    "in_app": "DELIVERED",
                    "email": "BLOCKED_CONFIGURATION",
                    "whatsapp": "BLOCKED_CONFIGURATION",
                    "sms": "BLOCKED_CONFIGURATION",
                }
                app.rollback()
        finally:
            _cleanup(admin, tenant_id)
