"""Tests for the copilot's SQL guard and the role migration behind it (#33).

These need no database. The guard is pure text handling, and the migration is
read from disk as text, so the whole file runs in CI before Postgres exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.copilot.sql_guard import (
    ALLOWED_PUBLIC_TABLES,
    MAX_LENGTH,
    UnsafeSql,
    describe_allowlist,
    validate,
)
from services.rules.query import SCOPE_SOURCES

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "packages" / "db" / "migrations" / "0007_copilot_role.sql"

# Tables that must never become readable, whatever else changes.
DENIED_TABLES = {
    "amazon_connection",
    "tenant_member",
    "tenant_quota",
    "audit_log",
    "selling_account",
}

OK = "select campaign_id, acos from copilot.mart_ppc_campaign_daily"


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def migration_code_lines() -> list[str]:
    """The migration with comment lines removed."""
    return [
        line
        for line in migration_sql().splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]


# --- the happy path -------------------------------------------------------


def test_a_plain_select_passes():
    assert "mart_ppc_campaign_daily" in validate(OK)


def test_limit_is_appended_when_missing():
    # Not security. A model asked for "all keywords" will try to pull a hundred
    # thousand rows into a context window that cannot hold them, and bill for it.
    assert validate(OK).rstrip().endswith("limit 500")


def test_an_existing_reasonable_limit_is_left_alone():
    assert validate(f"{OK} limit 20").rstrip().endswith("limit 20")


def test_an_absurd_limit_is_capped():
    assert validate(f"{OK} limit 999999").rstrip().endswith("limit 5000")


def test_a_cte_is_allowed_and_its_name_is_not_mistaken_for_a_table():
    # Without CTE tracking the guard would reject its own recommended style,
    # and the copilot would quietly stop using readable SQL.
    sql = (
        "with spend as (select campaign_id, sum(cost) c "
        "from copilot.mart_ppc_campaign_daily group by 1) "
        "select * from spend order by c desc"
    )
    assert "spend" in validate(sql)


def test_public_tables_may_be_read_bare_or_qualified():
    assert validate("select code from rule where enabled")
    assert validate("select code from public.rule where enabled")


# --- writes -----------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "insert into action (id) values (1)",
        "update rule set enabled = true",
        "delete from action",
        "drop table action",
        "alter table action add column x int",
        "truncate action",
        "grant select on action to public",
        "create view sneaky as select 1",
    ],
)
def test_write_statements_are_rejected(sql):
    with pytest.raises(UnsafeSql):
        validate(sql)


def test_select_into_is_rejected_because_it_creates_a_table():
    # The one that surprises people: SELECT is not always harmless.
    with pytest.raises(UnsafeSql, match="into"):
        validate("select * into stolen from public.rule")


def test_a_second_statement_is_rejected():
    with pytest.raises(UnsafeSql, match="one statement"):
        validate(f"{OK}; drop table action")


def test_comments_are_rejected():
    # The classic smuggling route past a validator that reads line by line.
    with pytest.raises(UnsafeSql, match="comments"):
        validate(f"{OK} -- ; drop table action")


# --- reach ------------------------------------------------------------------


def test_marts_cannot_be_read_directly():
    # marts has no RLS. A direct read that forgot a tenant filter would return
    # every tenant's spend, and would look perfectly normal doing it.
    with pytest.raises(UnsafeSql) as err:
        validate("select * from marts.mart_ppc_campaign_daily")
    assert "copilot.mart_ppc_campaign_daily" in str(err.value)


def test_every_rules_mart_is_reachable_only_through_the_copilot_schema():
    for scope, source in SCOPE_SOURCES.items():
        table = source[0]
        assert validate(f"select * from copilot.{table}"), scope
        with pytest.raises(UnsafeSql):
            validate(f"select * from marts.{table}")


@pytest.mark.parametrize("schema", ["pg_catalog", "information_schema", "raw"])
def test_closed_schemas_stay_closed(schema):
    with pytest.raises(UnsafeSql):
        validate(f"select * from {schema}.pg_tables")


@pytest.mark.parametrize("table", sorted(DENIED_TABLES))
def test_denied_tables_are_unreadable(table):
    with pytest.raises(UnsafeSql, match="allowlist"):
        validate(f"select * from {table}")


def test_a_query_that_reads_nothing_is_rejected():
    with pytest.raises(UnsafeSql, match="no table"):
        validate("select 1")


# --- functions and tricks ---------------------------------------------------


def test_set_tenant_cannot_be_called_from_generated_sql():
    # The application pins the tenant on the connection. If the query could set
    # it, the tenant boundary would be whatever the model felt like.
    with pytest.raises(UnsafeSql, match="set_tenant"):
        validate("select set_tenant('00000000-0000-0000-0000-000000000000')")


@pytest.mark.parametrize(
    "sql",
    [
        "select pg_sleep(300) from rule",
        "select pg_read_file('/etc/passwd') from rule",
        "select dblink('host=evil', 'select 1') from rule",
        "select set_config('app.tenant_id', 'x', false) from rule",
    ],
)
def test_dangerous_functions_are_rejected(sql):
    with pytest.raises(UnsafeSql, match="forbidden function"):
        validate(sql)


def test_a_string_literal_cannot_smuggle_a_keyword():
    # A campaign named "Update Bundle" is a real thing a seller would create,
    # and an action_type is literally called create_keyword. Neither is DDL.
    assert validate("select * from action where action_type = 'create_keyword'")
    assert validate("select * from copilot.mart_ppc_campaign_daily where campaign_name = 'Update Bundle'")


def test_an_over_long_query_is_rejected():
    with pytest.raises(UnsafeSql, match="limit is"):
        validate(OK + " or true" * MAX_LENGTH)


def test_the_refusal_explains_itself():
    # "Query rejected" teaches nobody anything, and a copilot that cannot say
    # why it refused looks broken rather than careful.
    with pytest.raises(UnsafeSql) as err:
        validate("select * from amazon_connection")
    assert "amazon_connection" in str(err.value)
    assert "sku_cost_ledger" in describe_allowlist()


# --- the code and the migration must agree ----------------------------------


def test_the_allowlist_matches_the_grants_in_migration_0007():
    # A grant added to the migration without a change here would widen what the
    # database allows while the validator stayed silent about it.
    granted = set(
        re.findall(
            r"grant\s+select\s+on\s+public\.(\w+)\s+to\s+axaty_copilot",
            migration_sql(),
            re.I,
        )
    )
    assert granted == set(ALLOWED_PUBLIC_TABLES)


def test_the_migration_never_grants_every_table():
    assert not re.search(r"grant\s+select\s+on\s+all\s+tables", migration_sql(), re.I)


def test_denied_tables_are_absent_from_both_lists():
    assert not (DENIED_TABLES & set(ALLOWED_PUBLIC_TABLES))
    for table in DENIED_TABLES:
        assert not re.search(
            rf"grant\s+select\s+on\s+public\.{table}\b", migration_sql(), re.I
        )


def test_the_role_is_read_only_at_the_server():
    # The single line that still protects us if every test above is wrong.
    assert re.search(
        r"alter\s+role\s+axaty_copilot\s+set\s+default_transaction_read_only\s*=\s*on",
        migration_sql(),
        re.I,
    )


def test_the_role_cannot_log_in_by_itself():
    assert re.search(r"create\s+role\s+axaty_copilot\s+nologin", migration_sql(), re.I)


def test_copilot_login_provisioning_copies_server_safety_defaults():
    instructions = (ROOT / ".env.example").read_text(encoding="utf-8")
    for setting, value in (
        ("default_transaction_read_only", "on"),
        ("statement_timeout", "'15s'"),
        ("idle_in_transaction_session_timeout", "'30s'"),
        ("lock_timeout", "'2s'"),
    ):
        assert re.search(
            rf"alter\s+role\s+axaty_copilot_app\s+set\s+{setting}\s*=\s*{value}",
            instructions,
            re.I,
        )


def test_no_password_is_committed():
    # The example CREATE USER lives in a comment on purpose. If it ever moves
    # into executable SQL, the password is in git forever.
    for line in migration_code_lines():
        assert "password" not in line.lower(), line


def test_the_copilot_views_carry_the_tenant_filter():
    # If refresh_views() ever emits a plain SELECT *, the view stops isolating
    # tenants and nothing else in the stack would notice.
    sql = migration_sql()
    assert "security_barrier = true" in sql
    assert "current_setting(''app.tenant_id''" in sql


def test_a_rollback_exists():
    down = ROOT / "packages" / "db" / "migrations" / "down" / "0007_copilot_role.sql"
    assert down.exists()
    assert "drop role axaty_copilot" in down.read_text(encoding="utf-8")
