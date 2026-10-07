import datetime as dt
import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from services.rules.ngrams import run_analysis

pytestmark = pytest.mark.db
# Creates a marts table, so never point this at a real warehouse.
TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://axaty:axaty@localhost:5432/axaty_test"
)
# Superusers bypass RLS, so isolation is asserted through the application role.
TEST_APP_DB = os.environ.get(
    "TEST_DATABASE_URL_APP", "postgresql://axaty_app:axaty_app@localhost:5432/axaty_test"
)
MARTS_DDL = """
create schema if not exists marts;
create table if not exists marts.mart_ppc_search_term_daily (
    tenant_id uuid not null, report_date date not null, campaign_id text,
    ad_group_id text, search_term text not null, impressions bigint, clicks bigint,
    cost numeric(18,4), attributed_orders_7d bigint, attributed_sales_7d numeric(18,4),
    is_already_negative boolean not null default false, is_settled boolean not null
);
"""


def _tenant(admin, tid, *, fresh):
    admin.execute("select set_tenant(%s)", (tid,))
    admin.execute("insert into tenant(id,name,slug) values(%s,'ngrams',%s)", (tid, f"n-{tid}"))
    if fresh:
        through = dt.date.today() - dt.timedelta(days=3)
        admin.execute(
            "insert into sync_watermark(tenant_id,dataset,last_complete_date,last_attempt_at,"
            "last_status) values(%s,'ads_sp_search_term_daily',%s,now(),'success')",
            (tid, through),
        )
        admin.execute(
            "insert into pipeline_run(tenant_id,dataset,date_to,status,finished_at)"
            " values(%s,'ads_sp_search_term_daily',%s,'success',now())",
            (tid, through),
        )


def _term(admin, tid, term, clicks, cost, orders=0, negative=False, days=(3, 4, 5)):
    for day in days:
        admin.execute(
            "insert into marts.mart_ppc_search_term_daily(tenant_id,report_date,campaign_id,"
            "search_term,impressions,clicks,cost,attributed_orders_7d,attributed_sales_7d,"
            "is_already_negative,is_settled) values(%s,%s,'C1',%s,%s,%s,%s,%s,%s,%s,true)",
            (tid, dt.date.today() - dt.timedelta(days=day), term, clicks * 20, clicks, cost,
             orders, orders * 30, negative),
        )
    # an unsettled day must never count
    admin.execute(
        "insert into marts.mart_ppc_search_term_daily(tenant_id,report_date,campaign_id,"
        "search_term,impressions,clicks,cost,attributed_orders_7d,attributed_sales_7d,"
        "is_settled) values(%s,current_date,'C1',%s,1000,500,500,0,0,false)",
        (tid, term),
    )


# account CVR = 9 / 252 clicks, so 90 zero-order clicks gives exp(-3.2) < 0.05
def _seed(admin, tid):
    _term(admin, tid, "hook and loop tape", clicks=34, cost=20, orders=3)
    _term(admin, tid, "free sample tape", clicks=15, cost=7)
    _term(admin, tid, "free sample velcro", clicks=15, cost=7)
    _term(admin, tid, "womens shoes red", clicks=10, cost=7)
    _term(admin, tid, "womens shoes blue", clicks=10, cost=7)
    _term(admin, tid, "junk phrase one", clicks=10, cost=7, negative=True)
    _term(admin, tid, "junk phrase two", clicks=10, cost=7, negative=True)


def test_ngram_run_persists_gated_findings_with_evidence_and_isolation():
    tenant_a, tenant_b, owner = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(TEST_DB, autocommit=True, row_factory=dict_row) as admin:
        admin.execute(MARTS_DDL)
        admin.execute(
            "insert into auth.auth_user(id,name,email) values(%s,'owner',%s)",
            (owner, f"{owner}@test"),
        )
        try:
            _tenant(admin, tenant_a, fresh=True)
            _tenant(admin, tenant_b, fresh=False)
            for tid in (tenant_a, tenant_b):
                admin.execute("select set_tenant(%s)", (tid,))
                _seed(admin, tid)
            admin.execute("select set_tenant(%s)", (tenant_a,))
            protection = admin.execute(
                "insert into entity_protection(tenant_id,entity_type,entity_value,policy,"
                "duration,reason,created_by) values(%s,'keyword','Womens Shoes','protect',"
                "'persistent','core keyword',%s) returning id",
                (tenant_a, owner),
            ).fetchone()["id"]

            with psycopg.connect(TEST_DB) as conn:
                run_a = run_analysis(conn, tenant_a)
                run_b = run_analysis(conn, tenant_b)

            assert run_a.status == "success" and run_a.queries_analyzed == 5
            assert run_b.status == "source_missing" and run_b.decisions == {}

            rows = {
                r["ngram"]: r
                for r in admin.execute(
                    "select * from search_term_ngram_recommendation where tenant_id=%s",
                    (tenant_a,),
                ).fetchall()
            }
            free = rows["free sample"]
            assert free["decision"] == "negative_phrase"
            assert (free["clicks"], free["query_count"], free["orders"]) == (90, 2, 0)
            assert [q["search_term"] for q in free["contributing_queries"]] == [
                "free sample tape",
                "free sample velcro",
            ]
            assert free["thresholds"]["min_queries"] == 2
            assert rows["free"]["decision"] == "manual_review"
            assert rows["womens shoes"]["decision"] == "protected"
            assert rows["womens shoes"]["protection_id"] == protection
            assert not any("junk" in ngram for ngram in rows)
            assert not any(ngram in rows for ngram in ("tape", "hook"))
            with pytest.raises(psycopg.errors.RaiseException):
                admin.execute(
                    "update search_term_ngram_recommendation set decision='covered' where id=%s",
                    (free["id"],),
                )

            with psycopg.connect(TEST_APP_DB, row_factory=dict_row) as app:
                app.execute("select set_tenant(%s)", (tenant_b,))
                assert app.execute(
                    "select count(*) n from search_term_ngram_recommendation"
                ).fetchone()["n"] == 0
                app.execute("select set_tenant(%s)", (tenant_a,))
                assert app.execute(
                    "select count(*) n from search_term_ngram_recommendation"
                ).fetchone()["n"] == len(rows)
        finally:
            for tid in (tenant_a, tenant_b):
                admin.execute("select set_tenant(%s)", (tid,))
                admin.execute(
                    "delete from marts.mart_ppc_search_term_daily where tenant_id=%s", (tid,)
                )
                admin.execute("delete from tenant where id=%s", (tid,))
            admin.execute("delete from auth.auth_user where id=%s", (owner,))
