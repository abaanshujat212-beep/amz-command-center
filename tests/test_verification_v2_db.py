import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def test_verification_snapshots_are_idempotent_and_tenant_isolated():
    first, second = uuid.uuid4(), uuid.uuid4()
    action = uuid.uuid4()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        for tenant_id in (first, second):
            admin.execute("insert into tenant(id,name,slug) values(%s,%s,%s)", (tenant_id, str(tenant_id), str(tenant_id)))
        admin.execute("insert into action(id,tenant_id,entity_type,entity_id,action_type,after_value,status,idempotency_key) values(%s,%s,'keyword','k1','set_bid','{\"value\":1}','applied','v2')", (action, first))
        admin.execute("insert into action_verification_snapshot(tenant_id,action_id,horizon_days,status,metric_keys,baseline_metrics,observed_metrics,window_before_start,window_before_end,window_after_start,window_after_end,reason_code) values(%s,%s,1,'INSUFFICIENT_DATA','[]','{}','{}',current_date-2,current_date-1,current_date-1,current_date,'WINDOW_NOT_MATURE')", (first, action))
    try:
        with psycopg.connect(APP_URL) as conn, conn.transaction():
            conn.execute("select set_tenant(%s)", (first,))
            assert conn.execute("select count(*) from action_verification_snapshot").fetchone()[0] == 1
            with pytest.raises(psycopg.errors.UniqueViolation):
                conn.execute("insert into action_verification_snapshot(tenant_id,action_id,horizon_days,status,metric_keys,baseline_metrics,observed_metrics,window_before_start,window_before_end,window_after_start,window_after_end,reason_code) values(%s,%s,1,'INSUFFICIENT_DATA','[]','{}','{}',current_date-2,current_date-1,current_date-1,current_date,'WINDOW_NOT_MATURE')", (first, action))
        with psycopg.connect(APP_URL) as conn, conn.transaction():
            conn.execute("select set_tenant(%s)", (second,))
            assert conn.execute("select count(*) from action_verification_snapshot").fetchone()[0] == 0
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute("delete from tenant where id=any(%s)", ([first, second],))
