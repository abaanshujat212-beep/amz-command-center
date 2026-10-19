import os
import uuid

import psycopg
import pytest

pytestmark=pytest.mark.db
ADMIN=os.environ.get("DATABASE_URL","postgresql://axaty:axaty@localhost:5432/axaty")
APP=os.environ.get("DATABASE_URL_APP","postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def test_budget_versions_audit_overlap_and_rls():
    a,b,user=uuid.uuid4(),uuid.uuid4(),uuid.uuid4()
    with psycopg.connect(ADMIN) as db:
        db.execute("insert into auth.auth_user(id,name,email) values(%s,'Budget owner',%s)",(user,f"{user}@test.local"))
        db.execute("insert into tenant(id,name,slug) values(%s,'A',%s),(%s,'B',%s)",(a,str(a),b,str(b)))
        row=db.execute("insert into portfolio_budget_limit(tenant_id,scope_type,scope_id,period_type,version,limit_amount,currency,timezone,effective_from,reason,created_by) values(%s,'portfolio','p1','monthly',1,1000,'GBP','Europe/London','2026-10-01','initial',%s) returning id",(a,user)).fetchone()[0]
        assert db.execute("select count(*) from portfolio_budget_limit_event where limit_id=%s",(row,)).fetchone()[0]==1
        db.commit()
        with pytest.raises(psycopg.errors.ExclusionViolation):
            db.execute("insert into portfolio_budget_limit(tenant_id,scope_type,scope_id,period_type,version,limit_amount,currency,timezone,effective_from,reason,created_by) values(%s,'portfolio','p1','monthly',2,900,'GBP','Europe/London','2026-10-15','overlap',%s)",(a,user))
        db.rollback()
        try:
            with psycopg.connect(APP) as app:
                app.execute("select set_tenant(%s)",(b,))
                assert app.execute("select count(*) from portfolio_budget_limit").fetchone()[0]==0
                app.execute("select set_tenant(%s)",(a,))
                assert app.execute("select count(*) from portfolio_budget_limit").fetchone()[0]==1
                with pytest.raises(psycopg.errors.RaiseException):
                    app.execute("update portfolio_budget_limit set limit_amount=1 where id=%s",(row,))
        finally:
            db.execute("delete from tenant where id=any(%s)", ([a, b],))
            db.execute("delete from auth.auth_user where id=%s", (user,))
            db.commit()
