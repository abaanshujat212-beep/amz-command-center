import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from services.actions.worker import fetch_approved

pytestmark = pytest.mark.db
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")


def test_concurrent_action_workers_skip_rows_claimed_by_another_worker():
    tenant_id = uuid.uuid4()
    action_id = uuid.uuid4()
    try:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as setup:
            setup.execute("select set_tenant(%s)", (tenant_id,))
            setup.execute(
                "insert into tenant(id,name,slug) values(%s,'worker-claim',%s)",
                (tenant_id, str(tenant_id)),
            )
            setup.execute(
                """insert into action(
                       id,tenant_id,entity_type,entity_id,action_type,before_value,
                       after_value,status,idempotency_key,approved_by,approved_at)
                   values(%s,%s,'keyword','K1','set_bid','{"value":1.0}',
                          '{"value":1.1}','approved',%s,%s,now())""",
                (action_id, tenant_id, str(action_id), uuid.uuid4()),
            )
            setup.commit()

        with (
            psycopg.connect(DATABASE_URL, row_factory=dict_row) as first,
            psycopg.connect(DATABASE_URL, row_factory=dict_row) as second,
        ):
            first.execute("select set_tenant(%s)", (tenant_id,))
            second.execute("select set_tenant(%s)", (tenant_id,))
            assert [action.id for action in fetch_approved(first, str(tenant_id), 10)] == [
                str(action_id)
            ]
            assert fetch_approved(second, str(tenant_id), 10) == []
            first.commit()
            assert [action.id for action in fetch_approved(second, str(tenant_id), 10)] == [
                str(action_id)
            ]
            second.rollback()
    finally:
        with psycopg.connect(DATABASE_URL) as cleanup:
            cleanup.execute("select set_tenant(%s)", (tenant_id,))
            cleanup.execute("delete from tenant where id=%s", (tenant_id,))
            cleanup.commit()
