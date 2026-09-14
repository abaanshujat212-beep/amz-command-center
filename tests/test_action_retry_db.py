import datetime as dt
import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def _seed(conn, tenant_id, action_id, error):
    conn.execute("select set_tenant(%s)", (tenant_id,))
    conn.execute("insert into tenant(id,name,slug) values(%s,'retry',%s)", (tenant_id, str(tenant_id)))
    conn.execute(
        """insert into action(id,tenant_id,entity_type,entity_id,action_type,
           after_value,status,idempotency_key)
           values(%s,%s,'keyword','K1','set_bid','{\"value\":1.1}','approved',%s)""",
        (action_id, tenant_id, str(action_id)),
    )
    conn.execute("update action set status='failed',error=%s where id=%s", (error, action_id))


def test_transient_failure_is_scheduled_atomically_with_audit():
    tenant_id, action_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as conn:
        _seed(conn, tenant_id, action_id, "HTTP 429 rate limit")
        row = conn.execute("select retry_count,failure_classification,next_attempt_at,dead_lettered_at from action where id=%s", (action_id,)).fetchone()
        assert row[0] == 1
        assert row[1] == "transient"
        assert row[2] is not None
        assert row[3] is None
        event = conn.execute("select event_type,retry_attempt from action_execution_event where action_id=%s", (action_id,)).fetchone()
        assert event == ("action.retry.scheduled", 1)
        conn.rollback()


def test_permanent_failure_dead_letters_without_scheduling():
    tenant_id, action_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as conn:
        _seed(conn, tenant_id, action_id, "unsupported capability")
        row = conn.execute("select failure_classification,next_attempt_at,dead_lettered_at from action where id=%s", (action_id,)).fetchone()
        assert row[0] == "capability"
        assert row[1] is None
        assert row[2] is not None
        event = conn.execute("select event_type from action_execution_event where action_id=%s", (action_id,)).fetchone()
        assert event[0] == "action.retry.exhausted"
        conn.rollback()


def test_retry_status_is_tenant_isolated_and_app_cannot_rewrite_audit():
    a, b, action_a, action_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        _seed(admin, a, action_a, "timeout")
        admin.commit()
        _seed(admin, b, action_b, "timeout")
        admin.commit()
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (a,))
                rows = app.execute("select id from v_action_retry_status").fetchall()
                assert rows == [(action_a,)]
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute("update action_execution_event set metadata='{}'")
        finally:
            for tenant_id in (a, b):
                admin.execute("select set_tenant(%s)", (tenant_id,))
                admin.execute("delete from action_execution_event where tenant_id=%s", (tenant_id,))
                admin.execute("delete from action where tenant_id=%s", (tenant_id,))
                admin.execute("delete from tenant where id=%s", (tenant_id,))
                admin.commit()


def test_retry_backoff_increases_and_is_bounded():
    tenant_id, action_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as conn:
        _seed(conn, tenant_id, action_id, "timeout")
        first = conn.execute("select next_attempt_at from action where id=%s", (action_id,)).fetchone()[0]
        conn.execute("update action set status='pending' where id=%s", (action_id,))
        conn.execute("update action set status='approved' where id=%s", (action_id,))
        before = dt.datetime.now(dt.timezone.utc)
        conn.execute("update action set status='failed',error='HTTP 503' where id=%s", (action_id,))
        second = conn.execute("select next_attempt_at from action where id=%s", (action_id,)).fetchone()[0]
        assert second > first
        assert second <= before + dt.timedelta(hours=1, minutes=1)
        conn.rollback()
