import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.db
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL = os.environ.get("DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def test_cogs_tables_are_tenant_isolated_and_immutable():
    a, b = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute("insert into tenant(id,name,slug) values(%s,'A',%s),(%s,'B',%s)", (a, str(a), b, str(b)))
        policy = admin.execute("insert into cogs_method_policy(tenant_id,sku,method,valid_from,version) values(%s,'SKU','fifo',current_date,1) returning id", (a,)).fetchone()[0]
        batch = admin.execute("insert into inventory_receipt_batch(tenant_id,sku,source_ref,received_at,quantity,unit_cost) values(%s,'SKU','R1',now(),10,2) returning id", (a,)).fetchone()[0]
        run = admin.execute("insert into cogs_calculation_run(tenant_id,marketplace_id,sku,policy_id,method,period_start,period_end,version,input_hash,status) values(%s,'A1F83G8C2ARO7P','SKU',%s,'fifo',current_date,current_date,1,'hash','complete') returning id", (a, policy)).fetchone()[0]
        admin.execute("insert into cogs_allocation(tenant_id,run_id,sale_ref,sold_at,batch_id,quantity,unit_cost,allocated_cost,currency,sequence) values(%s,%s,'S1',now(),%s,1,2,2,'GBP',0)", (a, run, batch))
        admin.commit()
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)", (b,))
                assert app.execute("select count(*) from cogs_calculation_run").fetchone()[0] == 0
                app.execute("select set_tenant(%s)", (a,))
                assert app.execute("select count(*) from cogs_allocation").fetchone()[0] == 1
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    app.execute("update cogs_allocation set allocated_cost=99")
        finally:
            admin.execute("delete from tenant where id=any(%s)", ([a, b],))
            admin.commit()


def test_backdated_recalculation_versions_instead_of_overwriting():
    tenant_id = uuid.uuid4()
    with psycopg.connect(ADMIN_URL) as conn:
        conn.execute("insert into tenant(id,name,slug) values(%s,'V',%s)", (tenant_id, str(tenant_id)))
        p1 = conn.execute("insert into cogs_method_policy(tenant_id,sku,method,valid_from,version) values(%s,'SKU','fifo','2026-01-01',1) returning id", (tenant_id,)).fetchone()[0]
        conn.execute("update cogs_method_policy set valid_to='2026-02-01' where id=%s", (p1,))
        p2 = conn.execute("insert into cogs_method_policy(tenant_id,sku,method,valid_from,version,supersedes_id) values(%s,'SKU','weighted_average','2026-02-01',2,%s) returning id", (tenant_id, p1)).fetchone()[0]
        assert conn.execute("select count(*) from cogs_method_policy where tenant_id=%s", (tenant_id,)).fetchone()[0] == 2
        assert p2 != p1
        conn.rollback()
