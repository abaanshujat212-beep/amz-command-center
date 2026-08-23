"""Validate SQL produced by the copilot before it reaches Postgres (#33).

This is a lexer, not a parser. It can be fooled by something clever enough, and
it is written on the assumption that one day it will be. That is why it is layer
one of five, and the only layer that lives in Python:

  1. this validator                      — rejects the obvious and the careless
  2. read-only transactions on the role  — the server refuses any write (0007)
  3. table-by-table grants               — tokens and identities are unreadable
  4. marts only through copilot views    — the tenant filter cannot be removed
  5. RLS on every public table           — rows are scoped whatever the query

If this file were perfect, layers 2 to 5 would still be required. If this file
fails completely, layers 2 to 5 still hold.
"""

from __future__ import annotations

import re

# Mirrors the grants in packages/db/migrations/0007_copilot_role.sql. The test
# suite parses that migration and asserts the two lists agree, so a grant added
# there without a change here fails the build rather than widening access
# quietly.
ALLOWED_PUBLIC_TABLES = frozenset(
    {
        "tenant",
        "tenant_settings",
        "rule",
        "rule_evaluation",
        "action",
        "alert",
        "pipeline_run",
        "sku_cost_ledger",
        "ads_profile",
        "sync_watermark",
        "schema_migrations",
    }
)

# Marts are reachable only as copilot.<mart_name>. Never marts.<mart_name>.
VIEW_SCHEMA = "copilot"

MAX_LENGTH = 4000
DEFAULT_LIMIT = 500
MAX_LIMIT = 5000

# Words that have no business in a read. 'into' is here because SELECT ... INTO
# creates a table, which surprises people who assume SELECT is always harmless.
FORBIDDEN_WORDS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "merge",
        "upsert",
        "truncate",
        "drop",
        "alter",
        "create",
        "replace",
        "grant",
        "revoke",
        "comment",
        "copy",
        "into",
        "call",
        "do",
        "execute",
        "prepare",
        "deallocate",
        "begin",
        "commit",
        "rollback",
        "savepoint",
        "set",
        "reset",
        "discard",
        "listen",
        "notify",
        "unlisten",
        "lock",
        "vacuum",
        "analyze",
        "reindex",
        "cluster",
        "refresh",
        "security",
        "authorization",
    }
)

# Functions that read files, burn time, or reach outside the database.
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "lo_import",
        "lo_export",
        "dblink",
        "dblink_exec",
        "pg_sleep",
        "pg_sleep_for",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "set_config",
        "set_tenant",
        "query_to_xml",
        "xmlserialize",
    }
)

# Schemas the copilot may never name directly.
FORBIDDEN_SCHEMAS = frozenset({"marts", "raw", "pg_catalog", "information_schema", "pg_toast"})

_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][\w$]*(?:\.[a-zA-Z_][\w$]*)?)", re.I)
_CTE_NAME = re.compile(r"(?:\bwith\b|,)\s+([a-zA-Z_][\w$]*)\s+as\s*\(", re.I)
_WORD = re.compile(r"[a-zA-Z_][\w$]*")
_FUNC_CALL = re.compile(r"([a-zA-Z_][\w$]*)\s*\(")
_TRAILING_LIMIT = re.compile(r"\blimit\s+(\d+)\s*$", re.I)


class UnsafeSql(ValueError):
    """Raised with a reason plain enough to show a user.

    The reason is deliberately specific. 'Query rejected' teaches nobody
    anything, and a copilot that cannot say why it refused looks broken rather
    than careful.
    """


def _strip_strings(sql: str) -> str:
    """Blank out string literals so their contents cannot trip the word checks.

    A campaign genuinely called "Update Bundle" must not be mistaken for an
    UPDATE statement.
    """
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def validate(sql: str) -> str:
    """Return the query, limit enforced, or raise UnsafeSql."""
    if not sql or not sql.strip():
        raise UnsafeSql("empty query")

    raw = sql.strip()
    if len(raw) > MAX_LENGTH:
        raise UnsafeSql(f"query is {len(raw)} characters; the limit is {MAX_LENGTH}")

    # Comments are rejected outright rather than stripped. The copilot has no
    # reason to emit them, and they are the standard way to hide a second
    # statement from a validator that only reads the beginning of a line.
    if "--" in raw or "/*" in raw:
        raise UnsafeSql("comments are not allowed in generated SQL")

    body = raw[:-1].strip() if raw.endswith(";") else raw
    if ";" in body:
        raise UnsafeSql("only one statement is allowed")

    scrubbed = _strip_strings(body)
    lowered = scrubbed.lower()

    first = _WORD.search(lowered)
    if first is None or first.group(0) not in ("select", "with"):
        raise UnsafeSql("only SELECT and WITH queries are allowed")

    words = set(_WORD.findall(lowered))
    hit = sorted(words & FORBIDDEN_WORDS)
    if hit:
        raise UnsafeSql(f"forbidden keyword: {hit[0]}")

    for func in _FUNC_CALL.findall(lowered):
        if func in FORBIDDEN_FUNCTIONS:
            raise UnsafeSql(f"forbidden function: {func}")

    cte_names = {name.lower() for name in _CTE_NAME.findall(scrubbed)}
    refs = [ref.lower() for ref in _TABLE_REF.findall(scrubbed)]
    if not refs:
        raise UnsafeSql("query reads no table")

    for ref in refs:
        if "." in ref:
            schema, table = ref.split(".", 1)
            if schema in FORBIDDEN_SCHEMAS:
                if schema == "marts":
                    raise UnsafeSql(
                        f"marts.{table} is not readable directly; use "
                        f"{VIEW_SCHEMA}.{table}, which filters by tenant"
                    )
                raise UnsafeSql(f"schema '{schema}' is not readable")
            if schema == VIEW_SCHEMA:
                continue
            if schema == "public" and table in ALLOWED_PUBLIC_TABLES:
                continue
            raise UnsafeSql(f"table '{ref}' is not in the copilot's allowlist")

        if ref in cte_names or ref in ALLOWED_PUBLIC_TABLES:
            continue
        raise UnsafeSql(f"table '{ref}' is not in the copilot's allowlist")

    return enforce_limit(body)


def enforce_limit(sql: str, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> str:
    """Cap the row count.

    An unbounded result is not a security problem; it is a cost and latency one.
    A model asked for "all keywords" will happily try to pull a hundred thousand
    rows into a context window that cannot hold them, and bill for the attempt.
    """
    match = _TRAILING_LIMIT.search(sql)
    if match is None:
        return f"{sql}\nlimit {default}"
    if int(match.group(1)) > maximum:
        return _TRAILING_LIMIT.sub(f"limit {maximum}", sql)
    return sql


def describe_allowlist() -> str:
    """Human-readable summary, for the copilot's own refusal messages."""
    tables = ", ".join(sorted(ALLOWED_PUBLIC_TABLES))
    return (
        f"Readable tables: {tables}. "
        f"Analytics marts are readable as {VIEW_SCHEMA}.<mart_name>, which return "
        f"only the current tenant's rows. Reads only, one statement, no comments."
    )
