import datetime as dt
import os
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

pytestmark=pytest.mark.db
ADMIN_URL=os.environ.get("DATABASE_URL","postgresql://axaty:axaty@localhost:5432/axaty")
APP_URL=os.environ.get("DATABASE_URL_APP","postgresql://axaty_app:axaty_app@localhost:5432/axaty")


def _seed(admin,tenant):
    admin.execute("select set_tenant(%s)",(tenant,))
    admin.execute("insert into tenant(id,name,slug) values(%s,'r04',%s)",(tenant,str(tenant)))
    rule=admin.execute("""insert into rule(tenant_id,code,name,scope,condition_jsonb,action_jsonb)
      values(%s,%s,'r04','keyword','{}','{}') returning id""",(tenant,f"r04-{tenant}")).fetchone()[0]
    run=uuid.uuid4()
    now=dt.datetime.now(dt.timezone.utc)
    admin.execute("""insert into optimizer_run(id,tenant_id,run_key,engine_version,configuration_version,objective_snapshot,strategy_snapshot,started_at)
      values(%s,%s,%s,'test','test','{}','{}',%s)""",(run,tenant,str(run),now))
    evaluation=admin.execute("""insert into rule_evaluation(tenant_id,rule_id,run_id,entity_type,entity_id,data_through,matched,metrics_snapshot,recommendation_type,confidence,risk,lookback_days,objective_snapshot,strategy_snapshot,economic_effect,expected_behavior)
      values(%s,%s,%s,'keyword','K1',current_date,true,'{}','bid_adjustment',0.75,'medium',14,'{}','{}','{}','{}') returning id""",(tenant,rule,run)).fetchone()[0]
    action=admin.execute("""insert into action(tenant_id,rule_id,evaluation_id,entity_type,entity_id,action_type,after_value,idempotency_key,recommendation_type,confidence,risk,lookback_days,objective_snapshot,strategy_snapshot,economic_effect,expected_behavior)
      values(%s,%s,%s,'keyword','K1','set_bid','{}',%s,'bid_adjustment',0.75,'medium',14,'{}','{}','{}','{}') returning id""",(tenant,rule,evaluation,str(run))).fetchone()[0]
    evidence=admin.execute("""insert into recommendation_evidence(tenant_id,optimizer_run_id,evaluation_id,action_id,evidence_kind,source_type,source_ref,observed_at,completeness,metric_keys)
      values(%s,%s,%s,%s,'metric_snapshot','fixture','fixture:1',%s,'complete',%s) returning id""",(tenant,run,evaluation,action,now,Jsonb(["clicks"]))).fetchone()[0]
    return run,action,evidence


def test_recommendation_evidence_is_tenant_scoped_immutable_and_run_finalizes_once():
    tenants=[uuid.uuid4(),uuid.uuid4()]
    user=uuid.uuid4()
    with psycopg.connect(ADMIN_URL,autocommit=True) as admin:
        admin.execute("insert into auth.auth_user(id,name,email) values(%s,'r04',%s)",(user,f"{user}@test"))
        refs=[_seed(admin,tenant) for tenant in tenants]
        try:
            with psycopg.connect(APP_URL) as app:
                app.execute("select set_tenant(%s)",(tenants[0],))
                assert app.execute("select count(*) from optimizer_run").fetchone()[0]==1
                assert app.execute("select count(*) from recommendation_evidence").fetchone()[0]==1
                with pytest.raises(psycopg.errors.RaiseException,match="immutable"):
                    app.execute("update recommendation_evidence set source_ref='changed'")
                app.rollback()
                app.execute("select set_tenant(%s)",(tenants[0],))
                run,action,_=refs[0]
                app.execute("update action set expires_at=expires_at+interval '1 hour' where id=%s",(action,))
                with pytest.raises(psycopg.errors.RaiseException,match="immutable"):
                    app.execute("update action set risk='high' where id=%s",(action,))
                app.rollback()
                app.execute("select set_tenant(%s)",(tenants[0],))
                app.execute("update optimizer_run set status='succeeded',finished_at=now(),duration_ms=1 where id=%s",(run,))
                with pytest.raises(psycopg.errors.RaiseException,match="finalized"):
                    app.execute("update optimizer_run set duration_ms=2 where id=%s",(run,))
        finally:
            for tenant in tenants:
                admin.execute("select set_tenant(%s)",(tenant,))
                admin.execute("delete from tenant where id=%s",(tenant,))
            admin.execute("delete from auth.auth_user where id=%s",(user,))
