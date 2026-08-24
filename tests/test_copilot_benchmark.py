"""T0 benchmark and refusal tests for the System Copilot (#33).

No database, no network, no API keys. That is the point: the one failing test this
repository had went unnoticed for days because nothing here had ever been run, and
a test that needs infrastructure is a test that does not run.

The live-database half lives in tests/test_copilot_isolation.py and skips cleanly.
"""

import re
from pathlib import Path

import pytest

from services.copilot import audit, questions, runner, sql_guard

RUNNER_SOURCE = Path(runner.__file__).read_text()

MART_QUESTIONS = {
    "account_last_7_days",
    "budget_throttled_campaigns",
    "keywords_burning_without_sales",
    "negate_candidates",
    "harvest_candidates",
    "economics_gaps",
}


# --- the benchmark --------------------------------------------------------


def test_the_benchmark_has_ten_questions():
    """ADR 006 promised ten. A benchmark that quietly shrinks proves nothing."""
    assert len(questions.T0_QUESTIONS) == 10


def test_question_keys_are_unique():
    keys = [q.key for q in questions.T0_QUESTIONS]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("question", questions.T0_QUESTIONS, ids=lambda q: q.key)
def test_every_benchmark_query_survives_the_guard(question):
    """If the guard rejects our own reference queries, the allowlist is wrong."""
    safe = sql_guard.validate(question.sql)
    assert "limit" in safe.lower()


@pytest.mark.parametrize("question", questions.T0_QUESTIONS, ids=lambda q: q.key)
def test_no_benchmark_query_averages_a_ratio(question):
    """avg(acos) weights a day with two clicks the same as a day with two
    thousand. Ratios must be recomputed from summed components."""
    lowered = question.sql.lower()
    assert "avg(" not in lowered, f"{question.key} averages something"


@pytest.mark.parametrize("question", questions.T0_QUESTIONS, ids=lambda q: q.key)
def test_ratios_are_divided_safely(question):
    """A zero denominator must produce null, never 0. 'ACOS 0%' reads as perfect
    performance when it actually means no sales at all."""
    lowered = question.sql.lower()
    if "/" in lowered:
        assert "nullif(" in lowered, f"{question.key} divides without nullif"


@pytest.mark.parametrize(
    "question",
    [q for q in questions.T0_QUESTIONS if q.key in MART_QUESTIONS],
    ids=lambda q: q.key,
)
def test_mart_questions_require_settled_data(question):
    """Unsettled days move under you: attribution keeps landing for ~3 days, so
    yesterday's ACOS improves on its own and any comparison to it is fiction."""
    assert "is_settled" in question.sql


@pytest.mark.parametrize("question", questions.T0_QUESTIONS, ids=lambda q: q.key)
def test_marts_are_read_through_the_copilot_views(question):
    """marts.* has no tenant filter. copilot.* does."""
    assert "marts." not in question.sql
    if "mart_" in question.sql:
        assert "copilot.mart_" in question.sql


@pytest.mark.parametrize("question", questions.T0_QUESTIONS, ids=lambda q: q.key)
def test_every_question_is_asked_in_both_languages(question):
    """Urdu is not decoration here: voice prompting (#36) is specified in Urdu and
    English, and these are the phrases it will be measured against."""
    assert question.question.strip()
    assert question.question_ur.strip()
    assert question.why.strip()


def test_the_mart_column_names_are_the_real_ones():
    """The marts expose attributed_sales_7d and attributed_orders_7d. Writing
    'sales' or 'orders' from memory produces a query that fails only once a
    database exists, which is far too late to be useful."""
    joined = " ".join(q.sql for q in questions.T0_QUESTIONS)
    assert "attributed_sales_7d" in joined
    assert "attributed_orders_7d" in joined
    assert not re.search(r"\bsum\(sales\)", joined)
    assert not re.search(r"\bsum\(orders\)", joined)


# --- the refusals --------------------------------------------------------


def test_there_are_refusal_cases_for_every_layer_that_matters():
    keys = {case.key for case in questions.MUST_REFUSE}
    assert {
        "refresh_tokens",
        "own_audit_trail",
        "identities",
        "marts_without_tenant_filter",
        "write",
        "second_statement",
        "comment_smuggling",
    } <= keys


@pytest.mark.parametrize("case", questions.MUST_REFUSE, ids=lambda c: c.key)
def test_forbidden_queries_are_refused(case):
    with pytest.raises(sql_guard.UnsafeSql):
        sql_guard.validate(case.sql)


@pytest.mark.parametrize("case", questions.MUST_REFUSE, ids=lambda c: c.key)
def test_refusals_say_something_specific(case):
    """'Query rejected' teaches nobody anything and makes a careful system look
    broken. Every refusal names the thing it objected to."""
    with pytest.raises(sql_guard.UnsafeSql) as exc:
        sql_guard.validate(case.sql)
    message = str(exc.value)
    assert len(message) > 15
    assert message.lower() != "query rejected"


def test_the_marts_refusal_teaches_the_fix():
    with pytest.raises(sql_guard.UnsafeSql) as exc:
        sql_guard.validate("select cost from marts.mart_ppc_campaign_daily")
    message = str(exc.value)
    assert "copilot.mart_ppc_campaign_daily" in message
    assert "tenant" in message


def test_a_campaign_named_like_a_keyword_is_not_a_write():
    """A real campaign called 'Update Bundle' must not read as an UPDATE. String
    literals are blanked before the keyword scan for exactly this reason."""
    safe = sql_guard.validate(
        "select cost from copilot.mart_ppc_campaign_daily "
        "where campaign_name = 'Update Bundle' limit 5"
    )
    assert "Update Bundle" in safe


# --- the runner ----------------------------------------------------------


def test_the_runner_contains_no_write_statement():
    """'We would never write from here' is a belief. This is a check."""
    lowered = RUNNER_SOURCE.lower()
    for pattern in (r"insert\s+into", r"update\s+\w+\s+set", r"delete\s+from"):
        assert not re.search(pattern, lowered), f"write statement in runner: {pattern}"


def test_rows_returned_to_a_model_are_bounded():
    """The SQL LIMIT can be defeated by a lateral join. A context window cannot."""
    assert 0 < runner.MAX_ROWS <= 5000


def test_a_proposal_cannot_be_made_at_answer_tier():
    req = audit.CopilotRequest(
        tenant_id="11111111-1111-1111-1111-111111111111",
        actor_user_id=None,
        question="should I raise this bid?",
        tier=audit.TIER_ANSWER,
    )
    answer = runner.Answer(columns=["acos"], rows=[(0.24,)], sql="select 1 limit 1")
    with pytest.raises(runner.CopilotRefusal):
        runner.propose(req, answer, "raise the bid to 1.20")


def test_a_proposal_never_applies_itself():
    req = audit.CopilotRequest(
        tenant_id="11111111-1111-1111-1111-111111111111",
        actor_user_id=None,
        question="what would you change?",
        tier=audit.TIER_PROPOSE,
    )
    answer = runner.Answer(columns=["acos"], rows=[(0.24,)], sql="select 1 limit 1")
    proposal = runner.propose(req, answer, "raise the budget to 24")
    assert proposal["applies_automatically"] is False
    assert "approval queue" in proposal["how_to_apply"]


def test_an_empty_answer_is_not_a_failure():
    """'No losing keywords' and 'the query matched nothing' are different claims."""
    answer = runner.Answer(columns=["keyword_text"], rows=[], sql="select 1 limit 1")
    assert answer.is_empty
    assert answer.row_count == 0


# --- audit ---------------------------------------------------------------


def test_a_request_must_name_a_tenant():
    with pytest.raises(ValueError):
        audit.CopilotRequest(tenant_id="", actor_user_id=None, question="anything")


def test_an_unknown_tier_is_refused():
    with pytest.raises(ValueError):
        audit.CopilotRequest(
            tenant_id="11111111-1111-1111-1111-111111111111",
            actor_user_id=None,
            question="anything",
            tier="T9",
        )


@pytest.mark.parametrize(
    "secret",
    [
        "Atzr|IQEBLjAsAhRmHjNgHpi0U-Dme37rR6CuUpSR",
        "Atza|IQEBLjAsAhRmHjNgHpi0U-Dme37rR6CuUpSR",
        "postgresql://axaty:hunter2@db:5432/axaty",
        "amzn1.application-oa2-client.abc123def456",
        "sk-abcdefghijklmnopqrstuvwx",
    ],
)
def test_credentials_pasted_into_a_question_are_redacted(secret):
    """The question is free text, and audit_log is the table meant to be kept for
    years. Redaction has to happen on the way in."""
    cleaned = audit.redact(f"why is this failing? {secret}")
    assert secret not in cleaned
    assert "redacted" in cleaned


def test_redaction_leaves_ordinary_questions_alone():
    question = "why did ACOS jump on Hook Tape Exact last week?"
    assert audit.redact(question) == question


def test_audit_refuses_to_write_as_the_copilot_itself(monkeypatch):
    """If both URLs are the same role, the audited party writes its own log."""
    monkeypatch.setenv("DATABASE_URL_APP", "postgresql://same:same@localhost/axaty")
    monkeypatch.setenv("DATABASE_URL_COPILOT", "postgresql://same:same@localhost/axaty")
    with pytest.raises(audit.AuditMisconfigured):
        audit.audit_connection_string()


def test_audit_needs_an_app_connection(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_APP", raising=False)
    with pytest.raises(audit.AuditMisconfigured):
        audit.audit_connection_string()


def test_refusals_and_errors_are_separate_actions():
    """A database outage must never be presented as a careful refusal."""
    assert audit.ACTION_REFUSED != audit.ACTION_ERROR
    assert issubclass(runner.CopilotRefusal, Exception)
    assert not issubclass(runner.CopilotRefusal, runner.CopilotError)
