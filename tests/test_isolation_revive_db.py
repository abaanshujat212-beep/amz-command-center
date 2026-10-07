import datetime as dt
import json
import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from services.rules.isolation_revive import run_analysis

pytestmark = pytest.mark.db
# Creates marts tables, so never point this at a real warehouse.
TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty_test"
)
# Superusers bypass RLS, so isolation is asserted through the application role.
TEST_APP_DB = os.environ.get(
    "TEST_DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty_test"
)
# Other suites create narrower versions of these tables; add what this one reads.
MARTS_DDL = """
create schema if not exists marts;
create table if not exists marts.mart_ppc_search_term_daily (
    tenant_id uuid not null, report_date date not null, search_term text not null,
    is_settled boolean not null
);
alter table marts.mart_ppc_search_term_daily
    add column if not exists campaign_id text, add column if not exists ad_group_id text,
    add column if not exists clicks bigint, add column if not exists cost numeric(18,4),
    add column if not exists attributed_orders_7d bigint,
    add column if not exists is_already_negative boolean not null default false;
create table if not exists marts.mart_ppc_keyword_daily (
    tenant_id uuid not null, report_date date not null, keyword_id text not null,
    is_settled boolean not null
);
alter table marts.mart_ppc_keyword_daily
    add column if not exists campaign_id text, add column if not exists ad_group_id text,
    add column if not exists keyword_text text, add column if not exists match_type text,
    add column if not exists keyword_status text, add column if not exists bid numeric(12,2),
    add column if not exists impressions bigint, add column if not exists clicks bigint,
    add column if not exists cost numeric(18,4),
    add column if not exists attributed_orders_7d bigint,
    add column if not exists attributed_sales_7d numeric(18,4),
    add column if not exists break_even_acos numeric;
"""
TODAY = dt.date.today()


def _day(n):
    return TODAY - dt.timedelta(days=n)


def _tenant(admin, tid, *, fresh):
    admin.execute("select set_tenant(%s)", (tid,))
    admin.execute("insert into tenant(id,name,slug) values(%s,'lifecycle',%s)", (tid, f"l-{tid}"))
    if not fresh:
        return None
    for dataset in ("ads_sp_search_term_daily", "ads_sp_keyword_daily"):
        admin.execute(
            "insert into sync_watermark(tenant_id,dataset,last_complete_date,last_attempt_at,"
            "last_status) values(%s,%s,%s,now(),'success')",
            (tid, dataset, _day(3)),
        )
        admin.execute(
            "insert into pipeline_run(tenant_id,dataset,date_to,status,finished_at)"
            " values(%s,%s,%s,'success',now())",
            (tid, dataset, _day(3)),
        )
    rule = admin.execute(
        "insert into rule(tenant_id,code,name,scope,condition_jsonb,action_jsonb)"
        " values(%s,'harvest','harvest','search_term','{}','{}') returning id",
        (tid,),
    ).fetchone()["id"]
    route = admin.execute(
        "insert into search_term_harvest_route(tenant_id,code,match_type,funnel_purpose,"
        "destination_campaign_id,destination_ad_group_id)"
        " values(%s,'generic_exact','exact','performance','C-EXACT','G-EXACT') returning id",
        (tid,),
    ).fetchone()["id"]
    return rule, route


def _promotion(admin, tid, rule, route, term, *, status="applied", days_ago=10):
    run = str(uuid.uuid4())
    ev = admin.execute(
        "insert into rule_evaluation(tenant_id,rule_id,run_id,entity_type,entity_id,"
        "data_through,matched,metrics_snapshot) values(%s,%s,%s,'search_term',%s,%s,true,'{}')"
        " returning id",
        (tid, rule, run, term, _day(3)),
    ).fetchone()["id"]
    action = admin.execute(
        "insert into action(tenant_id,rule_id,evaluation_id,entity_type,entity_id,action_type,"
        "after_value,status,applied_at,idempotency_key)"
        " values(%s,%s,%s,'search_term',%s,'create_keyword','{}',%s,%s,%s) returning id",
        (tid, rule, ev, term, status,
         None if status == "pending" else dt.datetime.now(dt.timezone.utc)
         - dt.timedelta(days=days_ago), run),
    ).fetchone()["id"]
    admin.execute(
        "insert into search_term_harvest_lineage(tenant_id,run_id,evaluation_id,action_id,"
        "route_id,route_code,search_term,normalized_term,brand_class,funnel_purpose,"
        "strategy_code,source_campaign_id,source_ad_group_id,destination_campaign_id,"
        "destination_ad_group_id,destination_match_type,routing_reason,evidence)"
        " values(%s,%s,%s,%s,%s,'generic_exact',%s,%s,'generic','performance','*','C-AUTO',"
        "'G-AUTO','C-EXACT','G-EXACT','exact','route generic_exact','{}')",
        (tid, run, ev, action, route, term, term),
    )


def _search_term(admin, tid, term, *, clicks=4, negative=False, days=(3, 4, 5)):
    for d in days:
        admin.execute(
            "insert into marts.mart_ppc_search_term_daily(tenant_id,report_date,campaign_id,"
            "ad_group_id,search_term,clicks,cost,attributed_orders_7d,is_already_negative,"
            "is_settled) values(%s,%s,'C-AUTO','G-AUTO',%s,%s,%s,0,%s,true)",
            (tid, _day(d), term, clicks, clicks * 0.5, negative),
        )


def _keyword(admin, tid, kid, text, *, status="enabled", days=(3, 4, 5), ad_group="G-EXACT",
             campaign="C-EXACT", impressions=50, clicks=5, cost=2.5, orders=0, sales=0.0,
             bid=0.80):
    for d in days:
        admin.execute(
            "insert into marts.mart_ppc_keyword_daily(tenant_id,report_date,campaign_id,"
            "ad_group_id,keyword_id,keyword_text,match_type,keyword_status,bid,impressions,"
            "clicks,cost,attributed_orders_7d,attributed_sales_7d,break_even_acos,is_settled)"
            " values(%s,%s,%s,%s,%s,%s,'exact',%s,%s,%s,%s,%s,%s,%s,0.30,true)",
            (tid, _day(d), campaign, ad_group, kid, text, status, bid, impressions, clicks,
             cost, orders, sales),
        )


OLD = (40, 41, 42, 43, 44)


def _winner(admin, tid, kid, text, *, status="paused", **kw):
    params = {"clicks": 10, "cost": 5, "orders": 1, "sales": 40.0, **kw}
    _keyword(admin, tid, kid, text, status=status, days=OLD, ad_group="G-REV",
             campaign="C-REV", **params)


def _seed_revive(admin, tid):
    _winner(admin, tid, "K-WIN", "blue tape")
    _winner(admin, tid, "K-LOSE", "red tape", cost=10, orders=0, sales=0.0)
    _winner(admin, tid, "K-THIN", "green tape", clicks=1)
    _winner(admin, tid, "K-COOL", "gold tape")
    _winner(admin, tid, "K-DUP", "silver tape")
    _winner(admin, tid, "K-DUP2", "Silver  Tape", status="enabled")


def test_isolation_and_revive_persist_separate_evidence_and_isolate_tenants():
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(TEST_DB, autocommit=True, row_factory=dict_row) as admin:
        admin.execute(MARTS_DDL)
        try:
            rule, route = _tenant(admin, tenant_a, fresh=True)
            _tenant(admin, tenant_b, fresh=False)
            admin.execute("select set_tenant(%s)", (tenant_a,))
            _promotion(admin, tenant_a, rule, route, "hook and loop tape")
            _promotion(admin, tenant_a, rule, route, "hook and loop tape", days_ago=9)
            _promotion(admin, tenant_a, rule, route, "sticky strips")
            _promotion(admin, tenant_a, rule, route, "velcro straps")
            _promotion(admin, tenant_a, rule, route, "queued term", status="pending")
            _keyword(admin, tenant_a, "K-DEST", "Hook and Loop Tape")
            _keyword(admin, tenant_a, "K-STICKY", "sticky strips", days=(20,))
            _keyword(admin, tenant_a, "K-VEL", "velcro straps")
            for term in ("hook and loop tape", "sticky strips", "queued term"):
                _search_term(admin, tenant_a, term)
            _search_term(admin, tenant_a, "velcro straps", negative=True)
            _seed_revive(admin, tenant_a)
            admin.execute(
                "insert into action(tenant_id,entity_type,entity_id,action_type,after_value,"
                "status,applied_at,idempotency_key) values(%s,'keyword','K-COOL','enable',"
                "'{}','applied',now()-interval '1 day',%s)",
                (tenant_a, str(uuid.uuid4())),
            )
            admin.execute("select set_tenant(%s)", (tenant_b,))
            _seed_revive(admin, tenant_b)

            actions_before = admin.execute(
                "select count(*) n from action where tenant_id=%s", (tenant_a,)
            ).fetchone()["n"]
            with psycopg.connect(TEST_DB) as conn:
                run_a = run_analysis(conn, tenant_a)
                run_b = run_analysis(conn, tenant_b)

            assert run_a.status == {"isolation_negative": "success", "revive_target": "success"}
            assert run_a.decisions == {
                "isolation_negative:recommended": 1,
                "isolation_negative:duplicate": 1,
                "isolation_negative:destination_no_traffic": 1,
                "isolation_negative:already_negative": 1,
                "revive_target:recommended": 1,
                "revive_target:poor_history": 1,
                "revive_target:thin_history": 1,
                "revive_target:cooldown": 1,
                "revive_target:duplicate": 1,
            }
            assert run_b.status == {
                "isolation_negative": "source_missing", "revive_target": "source_missing"}
            assert run_b.decisions == {}
            admin.execute("select set_tenant(%s)", (tenant_a,))
            assert admin.execute(
                "select count(*) n from action where tenant_id=%s", (tenant_a,)
            ).fetchone()["n"] == actions_before

            rows = admin.execute(
                "select * from search_term_lifecycle_recommendation where tenant_id=%s",
                (tenant_a,),
            ).fetchall()
            iso = next(r for r in rows if r["recommendation_type"] == "isolation_negative"
                       and r["decision"] == "recommended")
            assert (iso["ad_group_id"], iso["term"], iso["match_type"]) == (
                "G-AUTO", "hook and loop tape", "negative_exact")
            assert iso["lineage_id"] is not None and iso["proposed_bid"] is None
            assert iso["evidence"]["destination"]["keyword_id"] == "K-DEST"
            assert iso["evidence"]["source_since_applied"]["clicks"] == 12
            assert iso["evidence"]["lineage"]["route_code"] == "generic_exact"

            revive = next(r for r in rows if r["recommendation_type"] == "revive_target"
                          and r["decision"] == "recommended")
            assert (revive["keyword_id"], float(revive["proposed_bid"])) == ("K-WIN", 0.80)
            assert revive["lineage_id"] is None
            assert revive["evidence"]["history"]["orders"] == 5
            assert revive["thresholds"]["dormant_days"] == 14

            with pytest.raises(psycopg.errors.RaiseException):
                admin.execute(
                    "update search_term_lifecycle_recommendation set decision='blocked'"
                    " where id=%s",
                    (revive["id"],),
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                admin.execute(
                    "insert into search_term_lifecycle_recommendation(tenant_id,run_id,"
                    "recommendation_type,decision,subject_key,campaign_id,ad_group_id,"
                    "keyword_id,term,match_type,evidence,thresholds,data_through)"
                    " values(%s,%s,'revive_target','recommended','K-X','C','G','K-X','x',"
                    "'exact',%s,'{}',current_date)",
                    (tenant_a, str(uuid.uuid4()), json.dumps({})),
                )

            with psycopg.connect(TEST_APP_DB, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_b,))
                assert app.execute(
                    "select count(*) n from search_term_lifecycle_recommendation"
                ).fetchone()["n"] == 0
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert app.execute(
                    "select count(*) n from search_term_lifecycle_recommendation"
                ).fetchone()["n"] == len(rows) == 9
        finally:
            for tid in (tenant_a, tenant_b):
                admin.execute("select set_tenant(%s)", (tid,))
                for table in ("mart_ppc_search_term_daily", "mart_ppc_keyword_daily"):
                    admin.execute(f"delete from marts.{table} where tenant_id=%s", (tid,))
                admin.execute("delete from tenant where id=%s", (tid,))
