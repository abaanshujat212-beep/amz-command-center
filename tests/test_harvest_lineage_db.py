import datetime as dt
import json
import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from services.rules.engine import evaluate_tenant
from services.rules.starter_rules import STARTER_RULES

pytestmark = pytest.mark.db
# Creates marts tables, so never point this at a real warehouse.
TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty_test"
)
# Superusers bypass RLS, so isolation is asserted through the application role.
TEST_APP_DB = os.environ.get(
    "TEST_DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty_test"
)
HARVEST = next(r for r in STARTER_RULES if r["code"] == "harvest_converting_search_term")

MARTS_DDL = """
create schema if not exists marts;
create table if not exists marts.mart_ppc_search_term_daily (
    tenant_id uuid not null, report_date date not null, campaign_id text,
    ad_group_id text, search_term text not null, matched_keyword_id text,
    matched_match_type text, bid numeric(12,4), impressions bigint, clicks bigint,
    cost numeric(18,4), attributed_orders_7d bigint, attributed_sales_7d numeric(18,4),
    attributed_units_7d bigint, break_even_acos numeric, advertised_asin text,
    is_already_negative boolean not null default false,
    exists_as_exact boolean not null default false, is_settled boolean not null
);
create table if not exists marts.mart_ppc_keyword_daily (
    tenant_id uuid not null, report_date date not null, campaign_id text,
    ad_group_id text, keyword_id text not null, keyword_text text, match_type text,
    is_settled boolean not null
);
"""


def _tenant(admin, tid):
    admin.execute("select set_tenant(%s)", (tid,))
    admin.execute("insert into tenant(id,name,slug) values(%s,'harvest',%s)", (tid, f"h-{tid}"))
    admin.execute(
        "insert into tenant_settings(tenant_id,automation_enabled,dry_run) values(%s,true,true)",
        (tid,),
    )
    today = dt.date.today()
    admin.execute(
        "insert into sync_watermark(tenant_id,dataset,last_complete_date,last_attempt_at,"
        "last_status) values(%s,'ads_sp_search_term_daily',%s,now(),'success')",
        (tid, today - dt.timedelta(days=3)),
    )
    admin.execute(
        "insert into pipeline_run(tenant_id,dataset,date_to,status,finished_at)"
        " values(%s,'ads_sp_search_term_daily',%s,'success',now())",
        (tid, today - dt.timedelta(days=3)),
    )
    action = dict(HARVEST["action"], reason_template=HARVEST["reason_template"])
    admin.execute(
        "insert into rule(tenant_id,code,name,enabled,dry_run,priority,scope,condition_jsonb,"
        "action_jsonb,lookback_days,min_clicks,min_impressions)"
        " values(%s,%s,%s,true,true,%s,%s,%s,%s,%s,%s,%s)",
        (tid, HARVEST["code"], HARVEST["name"], HARVEST["priority"], HARVEST["scope"],
         json.dumps(HARVEST["condition"]), json.dumps(action), HARVEST["lookback_days"],
         HARVEST["min_clicks"], HARVEST["min_impressions"]),
    )


def _term(admin, tid, term, *, campaign="C-AUTO", ad_group="G-AUTO", orders=4, asin="B000TEST01"):
    for day in (3, 4, 5):
        admin.execute(
            "insert into marts.mart_ppc_search_term_daily(tenant_id,report_date,campaign_id,"
            "ad_group_id,search_term,matched_keyword_id,matched_match_type,bid,impressions,"
            "clicks,cost,attributed_orders_7d,attributed_sales_7d,attributed_units_7d,"
            "break_even_acos,advertised_asin,is_settled)"
            " values(%s,%s,%s,%s,%s,'K-BROAD','broad',0.80,400,20,10,%s,100,%s,0.30,%s,true)",
            (tid, dt.date.today() - dt.timedelta(days=day), campaign, ad_group, term,
             orders, orders, asin),
        )


def _route(admin, tid, code, *, funnel="performance", ad_group="G-EXACT", priority=100):
    admin.execute(
        "insert into search_term_harvest_route(tenant_id,code,priority,match_type,"
        "funnel_purpose,destination_campaign_id,destination_ad_group_id)"
        " values(%s,%s,%s,'exact',%s,'C-EXACT',%s)",
        (tid, code, priority, funnel, ad_group),
    )


def _evaluations(admin, tid):
    admin.execute("select set_tenant(%s)", (tid,))
    rows = admin.execute(
        "select entity_id,blocked_by,metrics_snapshot,reason_text from rule_evaluation"
        " where tenant_id=%s order by evaluated_at,entity_id",
        (tid,),
    ).fetchall()
    return rows


def test_harvest_routes_dedupes_records_lineage_and_isolates_tenants():
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(TEST_DB, autocommit=True, row_factory=dict_row) as admin:
        admin.execute(MARTS_DDL)
        try:
            for tid in (tenant_a, tenant_b):
                _tenant(admin, tid)
            admin.execute("select set_tenant(%s)", (tenant_a,))
            admin.execute(
                "insert into search_term_brand_term(tenant_id,term,brand_class)"
                " values(%s,'axaty','own_brand'),(%s,'velcro','competitor')",
                (tenant_a, tenant_a),
            )
            _route(admin, tenant_a, "generic_exact")
            _route(admin, tenant_a, "conquest_a", funnel="conquest", ad_group="G-CONQ-A")
            _route(admin, tenant_a, "conquest_b", funnel="conquest", ad_group="G-CONQ-B")
            _term(admin, tenant_a, "hook and loop tape", orders=4)
            _term(admin, tenant_a, "hook and loop tape", ad_group="G-BROAD", orders=6)
            _term(admin, tenant_a, "sticky strips")
            _term(admin, tenant_a, "velcro straps")
            _term(admin, tenant_a, "axaty tape")
            admin.execute(
                "insert into marts.mart_ppc_keyword_daily(tenant_id,report_date,keyword_id,"
                "keyword_text,match_type,is_settled) values(%s,current_date-3,'K-EX',"
                "' Sticky  Strips','exact',true)",
                (tenant_a,),
            )
            # tenant B owns a route that must never serve tenant A, and vice versa
            admin.execute("select set_tenant(%s)", (tenant_b,))
            _term(admin, tenant_b, "hook and loop tape")

            with psycopg.connect(TEST_DB) as conn:
                summary_a = evaluate_tenant(conn, tenant_a)
                summary_b = evaluate_tenant(conn, tenant_b)

            assert summary_a.proposed == 1
            assert summary_a.blocked == {
                "duplicate_target": 1,
                "harvest_route_conflict": 1,
                "harvest_route_missing": 1,
            }
            assert summary_b.proposed == 0
            assert summary_b.blocked == {"harvest_route_missing": 1}

            by_term = {r["entity_id"]: r for r in _evaluations(admin, tenant_a)}
            routed = by_term["hook and loop tape"]
            assert routed["blocked_by"] is None
            assert "Routing: route generic_exact" in routed["reason_text"]
            evidence = routed["metrics_snapshot"]["harvest_routing"]
            assert evidence["source"]["ad_group_id"] == "G-BROAD"
            assert evidence["destination"]["ad_group_id"] == "G-EXACT"
            assert by_term["sticky strips"]["blocked_by"] == "duplicate_target"
            assert by_term["velcro straps"]["blocked_by"] == "harvest_route_conflict"
            assert by_term["axaty tape"]["blocked_by"] == "harvest_route_missing"

            lineage = admin.execute(
                "select l.*, a.after_value from search_term_harvest_lineage l"
                " join action a on a.id=l.action_id where l.tenant_id=%s",
                (tenant_a,),
            ).fetchall()
            assert len(lineage) == 1
            row = lineage[0]
            assert (row["source_campaign_id"], row["source_ad_group_id"]) == ("C-AUTO", "G-BROAD")
            assert (row["destination_ad_group_id"], row["destination_match_type"]) == (
                "G-EXACT", "exact")
            assert (row["asin"], row["brand_class"], row["funnel_purpose"]) == (
                "B000TEST01", "generic", "performance")
            assert row["after_value"]["destination"]["route_code"] == "generic_exact"
            with pytest.raises(psycopg.errors.RaiseException):
                admin.execute(
                    "update search_term_harvest_lineage set routing_reason='x' where id=%s",
                    (row["id"],),
                )

            # a second run must not promote the same term again while it is open
            with psycopg.connect(TEST_DB) as conn:
                rerun = evaluate_tenant(conn, tenant_a)
            assert rerun.proposed == 0
            assert rerun.blocked["duplicate_target"] == 2

            with psycopg.connect(TEST_APP_DB, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_b,))
                for table in ("search_term_harvest_lineage", "search_term_harvest_route",
                              "search_term_brand_term"):
                    assert app.execute(f"select count(*) n from {table}").fetchone()["n"] == 0
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert app.execute(
                    "select count(*) n from search_term_harvest_lineage"
                ).fetchone()["n"] == 1
        finally:
            for tid in (tenant_a, tenant_b):
                admin.execute("select set_tenant(%s)", (tid,))
                for table in ("mart_ppc_search_term_daily", "mart_ppc_keyword_daily"):
                    admin.execute(f"delete from marts.{table} where tenant_id=%s", (tid,))
                admin.execute("delete from tenant where id=%s", (tid,))
