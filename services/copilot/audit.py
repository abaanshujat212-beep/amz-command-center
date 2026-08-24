"""Audit trail for the System Copilot (#33).

Every request is recorded, including the ones that are refused — a refusal is the
most interesting event in an audit log, because it is where someone tried
something the system would not do.

Who writes it
-------------
Not the copilot. Migration 0007 revokes audit_log from axaty_copilot and sets
default_transaction_read_only = on for that role, so the copilot physically
cannot write here. The trail is written over a separate connection using the app
role.

That is deliberate, not a workaround: a party that can edit its own audit log has
no audit log. This module refuses to run if both URLs resolve to the same role.

Two rows per request
--------------------
An intent row before execution, a terminal row after, sharing a request_id in the
jsonb payload. A single row written at the end disappears entirely when a request
hangs, crashes, or is killed mid-query — and 'no record' reads exactly like
'never asked'.

append-only
-----------
Rows are inserted, never updated. audit_log has no update path anywhere in this
codebase and should not gain one.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

ACTION_REQUEST = "copilot.request"
ACTION_RESULT = "copilot.result"
ACTION_REFUSED = "copilot.refused"
ACTION_ERROR = "copilot.error"

# Tiers from ADR 006. Recorded so that "has this ever proposed an action?" is a
# query rather than an opinion.
TIER_ANSWER = "T0"
TIER_DIAGNOSE = "T1"
TIER_PROPOSE = "T2"
TIERS = (TIER_ANSWER, TIER_DIAGNOSE, TIER_PROPOSE)

MAX_STORED_QUESTION = 2000
MAX_STORED_SQL = 4000


class AuditWriteFailed(RuntimeError):
    """The request must not proceed.

    Deliberately fatal. A copilot that answers without a trail is fine right up
    to the first disputed answer, at which point there is nothing to inspect.
    """


class AuditMisconfigured(RuntimeError):
    """The audit connection is not distinct from the copilot connection."""


# --- redaction ------------------------------------------------------------
#
# The question is free text. Users paste things into free text: refresh tokens
# while debugging, connection strings, API keys. audit_log is the one table meant
# to be retained for years, so redaction happens on the way in, not on the way
# out.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Atzr\|[A-Za-z0-9_\-]+"), "[redacted:refresh-token]"),
    (re.compile(r"Atza\|[A-Za-z0-9_\-]+"), "[redacted:access-token]"),
    (re.compile(r"postgres(?:ql)?://[^\s]+"), "[redacted:connection-string]"),
    (re.compile(r"amzn1\.application-oa2-client\.[A-Za-z0-9]+"), "[redacted:lwa-client]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "[redacted:api-key]"),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}"), "[redacted:api-key]"),
)


def redact(text: str | None) -> str | None:
    """Remove credential-shaped substrings. Never lossless, always safe."""
    if text is None:
        return None
    cleaned = text
    for pattern, replacement in _REDACTIONS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


@dataclass
class CopilotRequest:
    """One question, with everything needed to answer 'who asked what, as whom'."""

    tenant_id: str
    actor_user_id: str | None
    question: str
    tier: str = TIER_ANSWER
    channel: str = "chat"  # chat | voice | mcp — see #36, #37
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        if self.tier not in TIERS:
            raise ValueError(f"unknown tier {self.tier!r}; expected one of {TIERS}")
        if not self.tenant_id:
            # Refusing beats guessing: a request with no tenant would be logged
            # against the wrong account or not at all.
            raise ValueError("a copilot request must name a tenant")

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise AuditMisconfigured(
            f"{name} is not set. The copilot needs two connections: "
            "DATABASE_URL_COPILOT to read and DATABASE_URL_APP to write its audit trail."
        )
    return value


def audit_connection_string() -> str:
    """The app role. Asserted to differ from the copilot's own connection."""
    audit_url = _env("DATABASE_URL_APP")
    copilot_url = os.environ.get("DATABASE_URL_COPILOT")
    if copilot_url and audit_url.strip() == copilot_url.strip():
        raise AuditMisconfigured(
            "DATABASE_URL_APP and DATABASE_URL_COPILOT are identical, so the copilot "
            "would be writing its own audit trail. Migration 0007 exists to prevent "
            "exactly that; point them at different roles."
        )
    return audit_url


def _connect():
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - environment problem
        raise AuditWriteFailed(
            "psycopg is not installed: pip install 'psycopg[binary]'"
        ) from exc
    return psycopg.connect(audit_connection_string(), autocommit=False)


def _insert(
    tenant_id: str,
    actor_user_id: str | None,
    action: str,
    entity: str | None,
    payload: dict,
) -> None:
    """One append-only row, inside a transaction that sets the tenant first.

    set_tenant() must run in the same transaction as the insert: audit_log has
    FORCE ROW LEVEL SECURITY, so without it the insert is rejected by the policy
    rather than landing in the wrong tenant.
    """
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select set_tenant(%s)", (tenant_id,))
                cur.execute(
                    "insert into audit_log (tenant_id, actor_user_id, action, entity, after) "
                    "values (%s, %s, %s, %s, %s::jsonb)",
                    (
                        tenant_id,
                        actor_user_id,
                        action,
                        entity,
                        json.dumps(payload, default=str),
                    ),
                )
            conn.commit()
    except AuditMisconfigured:
        raise
    except Exception as exc:
        raise AuditWriteFailed(f"could not write {action} to audit_log: {exc}") from exc


def record_request(req: CopilotRequest) -> None:
    """Written BEFORE the query runs. Failure here stops the request."""
    _insert(
        req.tenant_id,
        req.actor_user_id,
        ACTION_REQUEST,
        f"copilot:{req.request_id}",
        {
            "request_id": req.request_id,
            "tier": req.tier,
            "channel": req.channel,
            "question": (redact(req.question) or "")[:MAX_STORED_QUESTION],
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
    )


def record_result(
    req: CopilotRequest,
    *,
    sql: str | None,
    row_count: int,
    truncated: bool = False,
    source: str = "sql",
) -> None:
    """Written after a successful answer.

    row_count is stored because 'the copilot said there were no losing keywords'
    and 'the query returned nothing' are different claims, and only one of them
    is a bug.
    """
    _insert(
        req.tenant_id,
        req.actor_user_id,
        ACTION_RESULT,
        f"copilot:{req.request_id}",
        {
            "request_id": req.request_id,
            "tier": req.tier,
            "source": source,
            "sql": (redact(sql) or "")[:MAX_STORED_SQL] if sql else None,
            "row_count": row_count,
            "truncated": truncated,
            "duration_ms": req.elapsed_ms,
        },
    )


def record_refusal(req: CopilotRequest, reason: str, *, sql: str | None = None) -> None:
    """A refusal is an event worth keeping, not a non-event.

    This is the row that answers 'has anything tried to read the token table?'
    and 'how often does the guard fire?'. A system that only logs successes
    cannot answer either.
    """
    _insert(
        req.tenant_id,
        req.actor_user_id,
        ACTION_REFUSED,
        f"copilot:{req.request_id}",
        {
            "request_id": req.request_id,
            "tier": req.tier,
            "reason": redact(reason),
            "sql": (redact(sql) or "")[:MAX_STORED_SQL] if sql else None,
            "duration_ms": req.elapsed_ms,
        },
    )


def record_error(req: CopilotRequest, exc: BaseException, *, sql: str | None = None) -> None:
    """Distinct from a refusal: the system broke, it did not decline.

    Collapsing the two would let a database outage look like a careful refusal,
    which is the most flattering possible way to hide a failure.
    """
    _insert(
        req.tenant_id,
        req.actor_user_id,
        ACTION_ERROR,
        f"copilot:{req.request_id}",
        {
            "request_id": req.request_id,
            "tier": req.tier,
            "error_type": type(exc).__name__,
            "error": redact(str(exc)),
            "sql": (redact(sql) or "")[:MAX_STORED_SQL] if sql else None,
            "duration_ms": req.elapsed_ms,
        },
    )


@contextmanager
def audited(req: CopilotRequest):
    """Guarantee an intent row and a terminal row for one request.

    Usage:

        with audited(req) as outcome:
            rows = run(sql)
            outcome.result(sql=sql, row_count=len(rows))

    If the body raises, an error row is written and the exception propagates. If
    the body records nothing, a terminal row is still written — a request with an
    intent row and no ending is the shape of a silent hang, and it should look
    like one in the log rather than like a clean session.
    """
    record_request(req)
    outcome = _Outcome(req)
    try:
        yield outcome
    except BaseException as exc:
        if not outcome.closed:
            record_error(req, exc, sql=outcome.sql)
            outcome.closed = True
        raise
    finally:
        if not outcome.closed:
            record_result(req, sql=outcome.sql, row_count=0, source="incomplete")
            outcome.closed = True


class _Outcome:
    """Small recorder handed to the caller by `audited`."""

    def __init__(self, req: CopilotRequest) -> None:
        self.req = req
        self.closed = False
        self.sql: str | None = None

    def result(
        self,
        *,
        sql: str | None = None,
        row_count: int = 0,
        truncated: bool = False,
        source: str = "sql",
    ) -> None:
        self.sql = sql or self.sql
        record_result(
            self.req, sql=self.sql, row_count=row_count, truncated=truncated, source=source
        )
        self.closed = True

    def refused(self, reason: str, *, sql: str | None = None) -> None:
        self.sql = sql or self.sql
        record_refusal(self.req, reason, sql=self.sql)
        self.closed = True
