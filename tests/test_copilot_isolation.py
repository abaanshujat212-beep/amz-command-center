"""Layers 2-5: what Postgres refuses, regardless of what Python decided (#33).

tests/test_copilot_benchmark.py proves the validator refuses. That is layer one,
it is a lexer, and it was written on the assumption that one day something will
outsmart it. These tests are the layers that still hold on that day:

  2. read-only transactions on the role      (0007)
  3. table-by-table grants and revokes       (0007)
  4. marts reachable only via copilot views  (0008)
  5. RLS on every public table               (0002)

Requires a provisioned database and skips otherwise, with a message naming the
missing piece. Run:

    make up && make migrate && make seed
    cd packages/dbt && dbt build
    psql -c "create user axaty_copilot_app with password 'devonly';"
    psql -c "grant axaty_copilot to axaty_copilot_app;"
    export DATABASE_URL_COPILOT=postgresql://axaty_copilot_app:devonly@localhost:5432/axaty
    pytest tests/test_copilot_isolation.py -v
"""

import os

import pytest

from services.copilot import runner, sql_guard

pytestmark = pytest.mark.db

psycopg = pytest.importorskip("psycopg", reason="pip install 'psycopg[binary]'")

COPILOT_URL = os.environ.get("DATABASE_URL_COPILOT")
OWNER_URL = os.environ.get("DATABASE_URL")

requires_copilot = pytest.mark.skipif(
    not COPILOT_URL,
    reason="DATABASE_URL_COPILOT is not set; create axaty_copilot_app and grant it "
    "the axaty_copilot role (see 0007_copilot_role.sql)",
)
requires_owner = pytest.mark.skipif(
    not OWNER_URL, reason="DATABASE_URL is not set; needed to look up two tenant ids"
)

VIEW = "copilot.mart_ppc_campaign_daily"


def copilot_conn():
    return psycopg.connect(COPILOT_URL, autocommit=False)


def scalar(cur):
    row = cur.fetchone()
    return None if row is None else row[0]


@pytest.fixture(scope="module")
def two_tenants():
    """Two seeded tenant ids, read as the owner because RLS stops the copilot
    from ever seeing more than one."""
    if not OWNER_URL:
        pytest.skip("DATABASE_URL is not set")
    with psycopg.connect(OWNER_URL) as conn, conn.cursor() as cur:
        cur.execute("select id from tenant order by created_at limit 2")
        rows = cur.fetchall()
    if len(rows) < 2:
        pytest.skip("fewer than two tenants; run `make seed` (it creates dev and dev-b)")
    return str(rows[0][0]), str(rows[1][0])


@pytest.fixture(scope="module")
def views_exist():
    if not COPILOT_URL:
        pytest.skip("DATABASE_URL_COPILOT is not set")
    with copilot_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(*) from information_schema.views "
            "where table_schema = 'copilot' and table_name = 'mart_ppc_campaign_daily'"
        )
        if not scalar(cur):
            pytest.skip(
                "copilot.mart_ppc_campaign_daily does not exist; run `dbt build`, "
                "which calls copilot.refresh_views() on completion"
            )
    return True


# --- layer 2: the role is read-only --------------------------------------


@requires_copilot
def test_the_session_is_what_it_claims_to_be():
    """Reading the connection string is not evidence. Ask the server."""
    with copilot_conn() as conn:
        identity = runner.boot_check(conn)
        conn.rollback()
    assert identity["read_only"] == "on"


@requires_copilot
def test_the_server_refuses_a_write_even_if_python_asks_for_one():
    """Layer one is a lexer and will eventually be fooled. This is what holds."""
    with copilot_conn() as conn:
        with pytest.raises(psycopg.Error), conn.cursor() as cur:
            cur.execute("create temporary table smuggled as select 1 as x")
        conn.rollback()


@requires_copilot
def test_the_role_carries_its_own_timeouts():
    """A copilot query is interactive. A 15s ceiling means a runaway join fails
    fast instead of holding a connection while someone waits."""
    with copilot_conn() as conn, conn.cursor() as cur:
        cur.execute("show statement_timeout")
        assert scalar(cur) == "15s"
        cur.execute("show idle_in_transaction_session_timeout")
        assert scalar(cur) == "30s"
        conn.rollback()


# --- layer 3: grants -----------------------------------------------------


@requires_copilot
@pytest.mark.parametrize(
    "table",
    ["amazon_connection", "audit_log", "tenant_member", "tenant_quota", "selling_account"],
)
def test_sensitive_tables_are_unreadable_by_the_role(table):
    """Revoked in 0007. amazon_connection holds refresh tokens; audit_log is the
    copilot's own trail and the audited party must not be able to read it."""
    with copilot_conn() as conn:
        with pytest.raises(psycopg.Error), conn.cursor() as cur:
            cur.execute(f"select * from {table} limit 1")
        conn.rollback()


@requires_copilot
def test_the_allowlist_matches_what_the_role_can_actually_read():
    """sql_guard's allowlist is a copy of the grants in 0007. A copy that is never
    compared is just a comment."""
    with copilot_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.table_privileges "
            "where grantee = 'axaty_copilot' and privilege_type = 'SELECT' "
            "and table_schema = 'public'"
        )
        granted = {row[0] for row in cur.fetchall()}
        conn.rollback()
    missing = sorted(sql_guard.ALLOWED_PUBLIC_TABLES - granted)
    assert missing == [], f"allowlisted but not granted: {missing}"


# --- layer 4: marts only through the views -------------------------------


@requires_copilot
def test_marts_cannot_be_read_directly():
    """marts has no RLS and no tenant filter. 0008 revokes the schema entirely."""
    with copilot_conn() as conn:
        with pytest.raises(psycopg.Error), conn.cursor() as cur:
            cur.execute("select * from marts.mart_ppc_campaign_daily limit 1")
        conn.rollback()


# --- layer 5: RLS --------------------------------------------------------


@requires_copilot
def test_without_a_tenant_the_views_return_nothing(views_exist):
    """Fail closed. Silence is the safe direction, but it also means a forgotten
    set_tenant() looks exactly like a quiet account — which is why every read runs
    inside a transaction that sets the tenant first."""
    with copilot_conn() as conn, conn.cursor() as cur:
        cur.execute(f"select count(*) from {VIEW}")
        assert scalar(cur) == 0
        conn.rollback()


@requires_copilot
@requires_owner
def test_each_tenant_sees_only_its_own_rows(two_tenants, views_exist):
    tenant_a, tenant_b = two_tenants
    with copilot_conn() as conn, conn.cursor() as cur:
        cur.execute("select set_tenant(%s)", (tenant_a,))
        cur.execute(f"select count(*) from {VIEW} where tenant_id <> %s", (tenant_a,))
        assert scalar(cur) == 0, "another tenant's rows are visible"
        conn.rollback()

        cur.execute("select set_tenant(%s)", (tenant_b,))
        cur.execute(f"select count(*) from {VIEW} where tenant_id <> %s", (tenant_b,))
        assert scalar(cur) == 0
        conn.rollback()


@requires_copilot
@requires_owner
def test_asking_for_another_tenant_by_id_returns_nothing(two_tenants, views_exist):
    """The interesting attack is not a missing filter, it is an explicit one. A
    prompt-injected question could name another tenant's id directly."""
    tenant_a, tenant_b = two_tenants
    with copilot_conn() as conn, conn.cursor() as cur:
        cur.execute("select set_tenant(%s)", (tenant_a,))
        cur.execute(f"select count(*) from {VIEW} where tenant_id = %s", (tenant_b,))
        assert scalar(cur) == 0
        conn.rollback()


@requires_copilot
@requires_owner
def test_the_tenant_setting_does_not_survive_the_transaction(two_tenants):
    """set_tenant uses set_config(..., true), which is transaction-local. If it
    leaked across transactions, a pooled connection would hand one tenant's scope
    to the next request."""
    tenant_a, _ = two_tenants
    with copilot_conn() as conn, conn.cursor() as cur:
        cur.execute("select set_tenant(%s)", (tenant_a,))
        cur.execute("select current_setting('app.tenant_id', true)")
        assert scalar(cur) == tenant_a
        conn.rollback()

        cur.execute("select current_setting('app.tenant_id', true)")
        assert scalar(cur) in (None, ""), "tenant scope leaked past its transaction"
        conn.rollback()


# --- end to end ----------------------------------------------------------


@requires_copilot
@requires_owner
def test_a_real_question_runs_and_leaves_an_audit_trail(two_tenants, views_exist):
    """The whole promise in one test: a benchmark question executes, and the
    request plus its outcome are both in audit_log afterwards."""
    if not os.environ.get("DATABASE_URL_APP"):
        pytest.skip("DATABASE_URL_APP is not set; the audit trail is written as the app role")

    from services.copilot import audit, questions

    tenant_a, _ = two_tenants
    req = audit.CopilotRequest(
        tenant_id=tenant_a,
        actor_user_id=None,
        question="how much did we spend in the last 7 settled days?",
    )
    answer = runner.run_sql(req, questions.by_key("account_last_7_days").sql)
    assert answer.sql.lower().startswith("with")

    with psycopg.connect(OWNER_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "select action from audit_log where entity = %s order by at",
            (f"copilot:{req.request_id}",),
        )
        actions = [row[0] for row in cur.fetchall()]
    assert actions == [audit.ACTION_REQUEST, audit.ACTION_RESULT]


@requires_copilot
@requires_owner
def test_a_refused_question_is_also_recorded(two_tenants):
    """A refusal is the most interesting row in an audit log: it is where someone
    tried something the system would not do."""
    if not os.environ.get("DATABASE_URL_APP"):
        pytest.skip("DATABASE_URL_APP is not set")

    from services.copilot import audit

    tenant_a, _ = two_tenants
    req = audit.CopilotRequest(
        tenant_id=tenant_a,
        actor_user_id=None,
        question="show me the amazon refresh tokens",
    )
    with pytest.raises(runner.CopilotRefusal):
        runner.run_sql(req, "select refresh_token_encrypted from amazon_connection")

    with psycopg.connect(OWNER_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "select action from audit_log where entity = %s order by at",
            (f"copilot:{req.request_id}",),
        )
        actions = [row[0] for row in cur.fetchall()]
    assert actions == [audit.ACTION_REQUEST, audit.ACTION_REFUSED]
