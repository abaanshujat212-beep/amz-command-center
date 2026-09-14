import datetime as dt
import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def _tenant(conn, name):
    tenant_id = uuid.uuid4()
    conn.execute("select set_tenant(%s)", (tenant_id,))
    conn.execute("insert into tenant(id,name,slug) values(%s,%s,%s)", (tenant_id, name, f"{name}-{tenant_id}"))
    return tenant_id


def _action(conn, tenant_id, action_id, *, status="pending", entity="K1", idem=None, applied_at=None):
    conn.execute("select set_tenant(%s)", (tenant_id,))
    conn.execute(
        """insert into action(id,tenant_id,entity_type,entity_id,action_type,
           after_value,status,idempotency_key,applied_at)
           values(%s,%s,'keyword',%s,'set_bid','{\"value\":1.1}',%s,%s,%s)""",
        (action_id, tenant_id, entity, status, idem or str(action_id), applied_at),
    )


def test_only_one_active_financial_proposal_per_tenant_entity():
    tenant_id, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        conn.execute("insert into tenant(id,name,slug) values(%s,'collision',%s)", (tenant_id, str(tenant_id)))
        _action(conn, tenant_id, first)
        with pytest.raises(psycopg.errors.UniqueViolation):
            _action(conn, tenant_id, second)
        conn.rollback()


def test_manual_signal_and_recent_axaty_change_are_explicit():
    tenant_id, action_id = uuid.uuid4(), uuid.uuid4()
    now = dt.datetime.now(dt.timezone.utc)
    with psycopg.connect(ADMIN_URL) as conn:
        conn.execute("select set_tenant(%s)", (tenant_id,))
        conn.execute("insert into tenant(id,name,slug) values(%s,'signals',%s)", (tenant_id, str(tenant_id)))
        conn.execute(
            """insert into entity_change_signal
               (tenant_id,entity_type,entity_id,source,change_kind,source_ref,observed_at,expires_at)
               values(%s,'keyword','K1','manual','bid','manual-1',%s,%s)""",
            (tenant_id, now, now + dt.timedelta(hours=2)),
        )
        row = conn.execute("select collision_kind,evidence from detect_action_collision(%s,'keyword','K1',null,%s)", (tenant_id, now)).fetchone()
        assert row[0] == "manual_change"
        assert row[1]["source_ref"] == "manual-1"
        conn.execute("delete from entity_change_signal where tenant_id=%s", (tenant_id,))
        _action(conn, tenant_id, action_id, status="applied", applied_at=now - dt.timedelta(hours=1))
        row = conn.execute("select collision_kind from detect_action_collision(%s,'keyword','K1',null,%s)", (tenant_id, now)).fetchone()
        assert row[0] == "recent_axaty_change"
        conn.rollback()


def test_change_signals_are_tenant_isolated_and_append_only_for_app():
    a, b = uuid.uuid4(), uuid.uuid4()
    now = dt.datetime.now(dt.timezone.utc)
    with psycopg.connect(ADMIN_URL) as admin:
        for tenant_id in (a, b):
            admin.execute("select set_tenant(%s)", (tenant_id,))
            admin.execute("insert into tenant(id,name,slug) values(%s,'tenant',%s)", (tenant_id, str(tenant_id)))
            admin.execute("insert into entity_change_signal(tenant_id,entity_type,entity_id,source,change_kind,source_ref,observed_at,expires_at) values(%s,'keyword','K1','manual','bid',%s,%s,%s)", (tenant_id, str(tenant_id), now, now + dt.timedelta(hours=1)))
        admin.commit()
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (a,))
                assert app.execute("select count(*) from entity_change_signal").fetchone()[0] == 1
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute("update entity_change_signal set evidence='{}'")
        finally:
            for tenant_id in (a, b):
                admin.execute("select set_tenant(%s)", (tenant_id,))
                admin.execute("delete from entity_change_signal where tenant_id=%s", (tenant_id,))
                admin.execute("delete from tenant where id=%s", (tenant_id,))
            admin.commit()
