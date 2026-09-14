import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def seed(admin, tenant_id, action_id, slug):
    admin.execute("insert into tenant(id,name,slug) values(%s,%s,%s)", (tenant_id, slug, slug))
    admin.execute(
        """insert into action(id,tenant_id,entity_type,entity_id,action_type,after_value,idempotency_key)
           values(%s,%s,'keyword','k1','set_bid','{\"value\":1.1}','idem-1')""",
        (action_id, tenant_id),
    )


def insert_event(conn, tenant_id, action_id, *, event_type="action.live_apply.started", dedupe="attempt-1"):
    return conn.execute(
        """insert into action_execution_event
           (tenant_id,action_id,actor_type,event_type,correlation_key,idempotency_key,
            dedupe_key,entity_type,entity_id)
           values(%s,%s,'worker',%s,'run-1','idem-1',%s,'keyword','k1') returning id""",
        (tenant_id, action_id, event_type, dedupe),
    ).fetchone()[0]


def test_execution_events_are_tenant_isolated_insert_only_and_structured():
    a, b, action_a, action_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        seed(admin, a, action_a, f"audit-{a}")
        seed(admin, b, action_b, f"audit-{b}")
        insert_event(admin, a, action_a)
        insert_event(admin, b, action_b)
        admin.commit()
        try:
            with psycopg.connect(APP_URL) as conn:
                conn.execute("select set_tenant(%s)", (a,))
                rows = conn.execute("select event_type,correlation_key from v_action_execution_history").fetchall()
                assert rows == [("action.live_apply.started", "run-1")]
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute("update action_execution_event set metadata='{}'")
        finally:
            admin.execute("delete from action_execution_event where tenant_id=any(%s)", ([a, b],))
            admin.execute("delete from tenant where id=any(%s)", ([a, b],))
            admin.commit()


def test_duplicate_delivery_is_idempotent_but_second_attempt_is_preserved():
    tenant_id, action_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as conn:
        seed(conn, tenant_id, action_id, f"dedupe-{tenant_id}")
        insert_event(conn, tenant_id, action_id)
        conn.execute(
            """insert into action_execution_event
               (tenant_id,action_id,actor_type,event_type,correlation_key,idempotency_key,
                dedupe_key,entity_type,entity_id)
               values(%s,%s,'worker','action.live_apply.started','run-1','idem-1',
                      'attempt-1','keyword','k1') on conflict do nothing""",
            (tenant_id, action_id),
        )
        insert_event(conn, tenant_id, action_id, dedupe="attempt-2")
        assert conn.execute("select count(*) from action_execution_event where tenant_id=%s", (tenant_id,)).fetchone()[0] == 2
        conn.rollback()


def test_action_state_rolls_back_when_audit_insert_fails():
    tenant_id, action_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        seed(admin, tenant_id, action_id, f"atomic-{tenant_id}")
        admin.execute("update action set status='approved' where id=%s", (action_id,))
        admin.commit()
        with pytest.raises(psycopg.errors.CheckViolation):
            with psycopg.connect(APP_URL) as conn:
                conn.execute("select set_tenant(%s)", (tenant_id,))
                conn.execute("update action set status='applied' where id=%s", (action_id,))
                insert_event(conn, tenant_id, action_id, event_type="invalid.event")
        assert admin.execute("select status from action where id=%s", (action_id,)).fetchone()[0] == "approved"
        admin.execute("delete from tenant where id=%s", (tenant_id,))
        admin.commit()
