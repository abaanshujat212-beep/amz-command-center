"""End-to-end test for the rules engine.

These are integration tests on purpose. The bugs this file exists to catch were
all boundary bugs -- Python column names vs SQL column names, engine vs
migration, rule metric names vs mart columns. A mocked database would have
happily reproduced every one of them.

Set TEST_DATABASE_URL to a throwaway database:

    createdb axaty_test
    psql axaty_test -f packages/db/migrations/0001_tenancy.sql   # ...and 0002-0005
    TEST_DATABASE_URL=postgresql://axaty:axaty@localhost:5432/axaty_test pytest tests/test_engine.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402

from services.rules.engine import evaluate_tenant  # noqa: E402
from services.rules.starter_rules import STARTER_RULES  # noqa: E402

# Deliberately NOT DATABASE_URL: this fixture creates tables in the marts
# schema, and pointing it at a real warehouse would be destructive.
TEST_DB = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB, reason="TEST_DATABASE_URL is not set"
)

# Columns are the contract between services/rules/query.py and the dbt marts.
# If query.py aggregates a column this DDL does not have, these tests fail --
# which is the point.
KEYWORD_DDL = """
create schema if not exists marts;
create table if not exists marts.mart_ppc_keyword_daily (
    tenant_id       uuid    not null,
    report_date     date    not null,
    campaign_id     text,
    ad_group_id     text,
    keyword_id      text    not null,
    keyword_text    text,
    match_type      text,
    bid             numeric(12,2),
    impressions     bigint,
    clicks          bigint,
    cost            numeric(18,4),
    attributed_orders_7d bigint,
    attributed_sales_7d  numeric(18,4),
    attributed_units_7d  bigint,
    top_of_search_impression_share numeric,
    break_even_acos numeric,
    contribution_margin_pct numeric,
    account_cvr     numeric,
    is_settled      boolean not null
);
"""

STARTERS = {r["code"]: r for r in STARTER_RULES}


def _rule_row(cur, tenant_id, code, *, priority=None, condition=None, scope=None):
    """Insert one ENABLED rule. Starter rules ship disabled; tests opt in."""
    src = STARTERS[code]
    action = dict(src["action"])
    action["reason_template"] = src["reason_template"]
    cur.execute(
        "insert into rule (tenant_id, code, name, enabled, dry_run, priority,"
        " scope, condition_jsonb, action_jsonb, lookback_days, min_clicks,"
        " min_impressions) values (%s,%s,%s,true,true,%s,%s,%s,%s,%s,%s,%s)"
        " returning id",
        (
            tenant_id,
            code,
            src["name"],
            priority if priority is not None else src["priority"],
            scope or src["scope"],
            json.dumps(condition or src["condition"]),
            json.dumps(action),
            src["lookback_days"],
            src["min_clicks"],
            src["min_impressions"],
        ),
    )
    return cur.fetchone()["id"]


def _keyword_day(cur, tenant_id, through, *, keyword_id, day, acos, bid=1.00,
                 clicks=40, impressions=2000, orders=5, break_even=0.30,
                 tos_share=0.35):
    """Insert one settled keyword-day whose ACOS is exactly `acos`."""
    sales = float(clicks) * 2.0          # arbitrary but non-zero
    cost = sales * acos
    cur.execute(
        "insert into marts.mart_ppc_keyword_daily (tenant_id, report_date,"
        " campaign_id, ad_group_id, keyword_id, keyword_text, match_type, bid,"
        " impressions, clicks, cost, attributed_orders_7d, attributed_sales_7d,"
        " attributed_units_7d, top_of_search_impression_share, break_even_acos,"
        " contribution_margin_pct, account_cvr, is_settled)"
        " values (%s,%s,'C1','G1',%s,'hook tape','exact',%s,%s,%s,%s,%s,%s,%s,"
        "%s,%s,0.42,0.09,true)",
        (
            tenant_id,
            through - dt.timedelta(days=day),
            keyword_id,
            bid,
            impressions,
            clicks,
            cost,
            orders,
            sales,
            orders,
            tos_share,
            break_even,
        ),
    )


@pytest.fixture
def conn():
    with psycopg.connect(TEST_DB) as c:
        with c.cursor() as cur:
            cur.execute(KEYWORD_DDL)
        c.commit()
        yield c


@pytest.fixture
def tenant(conn):
    """A tenant with automation ON and dry_run ON.

    Note the ordering: policy tenant_self on `tenant` means app.tenant_id must
    already equal the new row's id before the insert is allowed. RLS applies to
    the table owner too (FORCE ROW LEVEL SECURITY).
    """
    tid = str(uuid.uuid4())
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tid,))
        cur.execute(
            "insert into tenant (id, name) values (%s, 'test tenant')", (tid,)
        )
        cur.execute(
            "insert into tenant_settings (tenant_id, automation_enabled, dry_run)"
            " values (%s, true, true)",
            (tid,),
        )
    conn.commit()

    yield tid

    with conn.cursor() as cur:
        cur.execute("select set_tenant(%s)", (tid,))
        cur.execute("delete from marts.mart_ppc_keyword_daily where tenant_id = %s", (tid,))
        for table in ("action", "rule_evaluation", "rule", "pipeline_run",
                      "tenant_settings"):
            cur.execute(f"delete from {table} where tenant_id = %s", (tid,))
        cur.execute("delete from tenant where id = %s", (tid,))
    conn.commit()


def _through(now):
    # newest settled date, matching TenantGuardConfig.settlement_lag_days
    return now.date() - dt.timedelta(days=3)


def _actions(conn, tenant_id):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant_id,))
        cur.execute(
            "select entity_id, action_type, status, before_value, after_value,"
            " clamped from action where tenant_id = %s order by entity_id",
            (tenant_id,),
        )
        return cur.fetchall()


# --------------------------------------------------------------------------
# The regression that matters most: before the fix, query.py returned every
# aggregated row and the engine defaulted `matched` to True. A losing keyword
# would have been proposed for a BID INCREASE.
# --------------------------------------------------------------------------
def test_unprofitable_keyword_does_not_match_a_scale_up_rule(conn, tenant):
    now = dt.datetime.now(dt.timezone.utc)
    through = _through(now)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant,))
        _rule_row(cur, tenant, "raise_bid_profitable")
        # ACOS 0.50 against a 0.30 break-even: clearly losing money.
        for day in range(1, 4):
            _keyword_day(cur, tenant, through, keyword_id="K_LOSER",
                         day=day, acos=0.50)
    conn.commit()

    summary = evaluate_tenant(conn, tenant, now=now, through=through)

    assert summary.entities_evaluated == 1, "the keyword should be aggregated"
    assert summary.matched == 0, "a losing keyword must not match a bid-up rule"
    assert summary.proposed == 0
    assert _actions(conn, tenant) == []


def test_profitable_keyword_produces_exactly_one_pending_action(conn, tenant):
    now = dt.datetime.now(dt.timezone.utc)
    through = _through(now)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant,))
        _rule_row(cur, tenant, "raise_bid_profitable")
        # ACOS 0.15 < break_even 0.30 * 0.7 = 0.21
        for day in range(1, 4):
            _keyword_day(cur, tenant, through, keyword_id="K_WINNER",
                         day=day, acos=0.15, bid=1.00)
    conn.commit()

    summary = evaluate_tenant(conn, tenant, now=now, through=through)

    assert summary.matched == 1
    assert summary.proposed == 1

    rows = _actions(conn, tenant)
    assert len(rows) == 1
    a = rows[0]
    assert a["entity_id"] == "K_WINNER"
    assert a["action_type"] == "set_bid"
    assert a["status"] == "pending", "nothing may skip the approval queue"
    # bid 1.00 * 1.10, inside the +/-25% clamp
    assert float(a["after_value"]["value"]) == pytest.approx(1.10)
    assert a["clamped"] is False


def test_rule_with_unknown_metric_is_disabled_not_retried(conn, tenant):
    now = dt.datetime.now(dt.timezone.utc)
    through = _through(now)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant,))
        rule_id = _rule_row(
            cur, tenant, "raise_bid_profitable",
            condition={">": [{"var": "profit_per_vibe"}, 1]},
        )
        _keyword_day(cur, tenant, through, keyword_id="K1", day=1, acos=0.15)
    conn.commit()

    summary = evaluate_tenant(conn, tenant, now=now, through=through)

    assert summary.proposed == 0
    assert any("profit_per_vibe" in e for e in summary.errors)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant,))
        cur.execute("select enabled from rule where id = %s", (rule_id,))
        assert cur.fetchone()["enabled"] is False


def test_higher_priority_rule_claims_the_entity(conn, tenant):
    """Two rules want the same keyword. Only one change may be proposed."""
    now = dt.datetime.now(dt.timezone.utc)
    through = _through(now)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant,))
        # Same condition, different priority. Lower number runs first.
        _rule_row(cur, tenant, "raise_bid_profitable", priority=10)
        _rule_row(cur, tenant, "rescue_impression_starved", priority=99,
                  condition=STARTERS["raise_bid_profitable"]["condition"])
        for day in range(1, 4):
            _keyword_day(cur, tenant, through, keyword_id="K_CONTESTED",
                         day=day, acos=0.15)
    conn.commit()

    summary = evaluate_tenant(conn, tenant, now=now, through=through)

    assert summary.rules_run == 2
    assert summary.matched == 2, "both rules match the same keyword"
    assert summary.proposed == 1, "but only the first may act on it"

    rows = _actions(conn, tenant)
    assert len(rows) == 1


def test_run_summary_is_written_to_pipeline_run(conn, tenant):
    """Regression: the engine used to insert non-existent column names here,
    which rolled back every proposal the run had just created."""
    now = dt.datetime.now(dt.timezone.utc)
    through = _through(now)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant,))
        _rule_row(cur, tenant, "raise_bid_profitable")
        for day in range(1, 4):
            _keyword_day(cur, tenant, through, keyword_id="K_WINNER",
                         day=day, acos=0.15)
    conn.commit()

    summary = evaluate_tenant(conn, tenant, now=now, through=through)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select set_tenant(%s)", (tenant,))
        cur.execute(
            "select dataset, status, rows_loaded, detail from pipeline_run"
            " where tenant_id = %s and dataset = 'rules_evaluate'",
            (tenant,),
        )
        run = cur.fetchone()

    assert run is not None, "the run summary must survive the commit"
    assert run["status"] == "success"
    assert run["rows_loaded"] == summary.proposed == 1
    assert run["detail"]["matched"] == 1
