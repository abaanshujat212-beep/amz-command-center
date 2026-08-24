"""The only way a copilot request reaches the database (#33).

Pipeline for every request, in order:

  1. sql_guard.validate   — lexer-level refusal, limit enforced
  2. audit.record_request — written before execution; failure stops the request
  3. boot_check           — the connection proves it is the copilot role, read-only
  4. set_tenant           — in the same transaction as the query, always
  5. execute + fetch      — bounded rows
  6. audit terminal row   — result, refusal, or error; never nothing

There is no write path in this module. Not a disabled one — none. The copilot may
propose, in words, with the SQL it used; a human then acts through the approval
queue (#22). See ADR 006 and the March 2026 Amazon policy on AI-driven bid
decisions in third-party tools.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from services.copilot import audit, sql_guard, system_map

# Hard ceiling on rows returned to a model. sql_guard already caps the SQL, but
# a LIMIT can be defeated by a lateral join, and a context window cannot.
MAX_ROWS = 1000


class CopilotRefusal(Exception):
    """A deliberate 'no', safe to show the user verbatim.

    Separate from CopilotError so that a database outage can never be presented
    as a careful refusal. That confusion would make an incident look like good
    judgement.
    """


class CopilotError(RuntimeError):
    """Something broke. The user should be told it broke."""


class PrivilegeMismatch(CopilotError):
    """The connection is not the read-only copilot role."""


@dataclass
class Answer:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    sql: str
    truncated: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def is_empty(self) -> bool:
        """Empty is a finding, not a failure.

        'No losing keywords' and 'the query matched nothing' read identically to
        a model, so callers must state which one they mean. Every zero-vs-null
        bug in this codebase started by not distinguishing them.
        """
        return not self.rows


def connection_string() -> str:
    url = os.environ.get("DATABASE_URL_COPILOT")
    if not url:
        raise CopilotError(
            "DATABASE_URL_COPILOT is not set. The copilot must connect as "
            "axaty_copilot_app (which holds the NOLOGIN axaty_copilot role), never as "
            "the database owner and never with DATABASE_URL."
        )
    return url


def _connect():
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - environment problem
        raise CopilotError("psycopg is not installed: pip install 'psycopg[binary]'") from exc
    return psycopg.connect(connection_string(), autocommit=False)


def boot_check(conn) -> dict[str, str]:
    """Ask the server what we actually are, and refuse if it is not the copilot.

    Reading the connection string is not evidence. The string can point at the
    owner, and every query would then succeed while quietly ignoring RLS — the
    same failure that reached main once already in apps/web/lib/db.ts.

    Two things are verified with the server's own answers:
      * transaction_read_only is on   (0007 sets it on the role)
      * the session is not a superuser and not the owner
    """
    with conn.cursor() as cur:
        cur.execute(
            "select current_user, "
            "       current_setting('transaction_read_only'), "
            "       (select rolsuper from pg_roles where rolname = current_user)"
        )
        row = cur.fetchone()
    if row is None:  # pragma: no cover - impossible from Postgres
        raise PrivilegeMismatch("the server returned no identity for this session")
    user, read_only, is_super = row[0], str(row[1]).lower(), bool(row[2])

    if is_super:
        raise PrivilegeMismatch(
            f"connected as superuser '{user}'. RLS does not apply to superusers, so "
            "every tenant's rows would be readable and nothing would error. Point "
            "DATABASE_URL_COPILOT at axaty_copilot_app."
        )
    if read_only != "on":
        raise PrivilegeMismatch(
            f"session for '{user}' is not read-only (transaction_read_only={read_only}). "
            "Migration 0007 sets this on the axaty_copilot role; a session without it "
            "is not that role."
        )
    return {"user": user, "read_only": read_only}


def run_sql(req: audit.CopilotRequest, sql: str) -> Answer:
    """Validate, audit, execute, audit again. The whole contract."""
    with audit.audited(req) as outcome:
        try:
            safe_sql = sql_guard.validate(sql)
        except sql_guard.UnsafeSql as exc:
            reason = f"{exc}. {sql_guard.describe_allowlist()}"
            outcome.refused(reason, sql=sql)
            raise CopilotRefusal(reason) from exc

        try:
            with _connect() as conn:
                boot_check(conn)
                with conn.cursor() as cur:
                    # Same transaction as the query. A set_tenant() in a
                    # different transaction is not scoping anything: the setting
                    # is transaction-local by design (see 0002).
                    cur.execute("select set_tenant(%s)", (req.tenant_id,))
                    cur.execute(safe_sql)
                    columns = [d.name for d in (cur.description or [])]
                    fetched = cur.fetchmany(MAX_ROWS + 1)
                # Read-only work is rolled back, not committed. Nothing to keep,
                # and it leaves no idle transaction holding locks.
                conn.rollback()
        except PrivilegeMismatch:
            raise
        except Exception as exc:
            raise CopilotError(f"query failed: {exc}") from exc

        truncated = len(fetched) > MAX_ROWS
        rows = list(fetched[:MAX_ROWS])
        outcome.result(sql=safe_sql, row_count=len(rows), truncated=truncated)

    answer = Answer(columns=columns, rows=rows, sql=safe_sql, truncated=truncated)
    if truncated:
        answer.notes.append(
            f"showing the first {MAX_ROWS} rows; the result was larger. "
            "Say so rather than summarising a partial set as if it were complete."
        )
    return answer


def refuse_unknown(req: audit.CopilotRequest, subject: str) -> str:
    """The answer when something is not in the system map.

    Returned as a string rather than raised, because 'I do not know' is a correct
    answer to a fair question and should not read like a crash. It is still
    audited as a refusal, so the gaps are countable.
    """
    reason = (
        f"'{subject}' is {system_map.NOT_IN_MAP}. "
        "The map is generated from the migrations, the rule catalog, the dbt models "
        "and the endpoint catalog — if it is not there, it does not exist in this "
        "system, and guessing would be worse than saying so."
    )
    audit.record_refusal(req, reason)
    return reason


def propose(req: audit.CopilotRequest, answer: Answer, recommendation: str) -> dict:
    """Package a T2 proposal. Writes nothing, anywhere.

    The returned dict is text and evidence for a human. Creating an `action` row
    is the rules engine's job (services/rules/engine.py) under its guardrails, and
    approving one is a person's job in the queue (#22). Letting the copilot insert
    an action would put an LLM inside the write path with none of the guardrails
    the engine applies — cooldowns, blast radius, bounds, kill switch.
    """
    if req.tier != audit.TIER_PROPOSE:
        raise CopilotRefusal(
            f"a proposal requires tier {audit.TIER_PROPOSE}; this request is {req.tier}"
        )
    return {
        "request_id": req.request_id,
        "recommendation": recommendation,
        "evidence_sql": answer.sql,
        "evidence_rows": answer.row_count,
        "applies_automatically": False,
        "how_to_apply": (
            "This is a recommendation only. Bid and budget changes reach Amazon "
            "exclusively through the rules engine and the approval queue, where they "
            "are logged, clamped and reversible."
        ),
    }
