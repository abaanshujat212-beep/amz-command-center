"""T0 benchmark and refusal tests for the System Copilot (#33)."""

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


def test_the_benchmark_has_expected_questions():
    keys = {q.key for q in questions.T0_QUESTIONS}
    assert len(questions.T0_QUESTIONS) >= 10
    assert {"product_opportunities", "sqp_harvest_opportunities"} <= keys


def test_question_keys_are_unique():
    keys = [q.key for q in questions.T0_QUESTIONS]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("question", questions.T0_QUESTIONS, ids=lambda q: q.key)
def test_every_benchmark_query_survives_the_guard(question):
    safe = sql_guard.validate(question.sql)
    assert "limit" in safe.lower()


@pytest.mark.parametrize("question", questions.T0_QUESTIONS, ids=lambda q: q.key)
def test_no_benchmark_query_averages_a_ratio(question):
    lowered = question.sql.lower()
    assert "avg(" not in lowered, f"{question.key} averages something"


@pytest.mark.parametrize("question", questions.T0_QUESTIONS, ids=lambda q: q.key)
def test_ratios_are_divided_safely(question):
    lowered = question.sql.lower()
    if "/" in lowered:
        assert "nullif(" in lowered, f"{question.key} divides without nullif"


@pytest.mark.parametrize("question", [q for q in questions.T0_QUESTIONS if q.key in MART_QUESTIONS], ids=lambda q: q.key)
def test_mart_questions_require_settled_data(question):
    assert "is_settled" in question.sql


@pytest.mark.parametrize("question", questions.T0_QUESTIONS, ids=lambda q: q.key)
def test_marts_are_read_through_the_copilot_views(question):
    assert "marts." not in question.sql
    if "mart_" in question.sql:
        assert "copilot.mart_" in question.sql


@pytest.mark.parametrize("question", questions.T0_QUESTIONS, ids=lambda q: q.key)
def test_every_question_is_asked_in_both_languages(question):
    assert question.question.strip()
    assert question.question_ur.strip()
    assert question.why.strip()


def test_the_mart_column_names_are_the_real_ones():
    joined = " ".join(q.sql for q in questions.T0_QUESTIONS)
    assert "attributed_sales_7d" in joined
    assert "attributed_orders_7d" in joined
    assert not re.search(r"\bsum\(sales\)", joined)
    assert not re.search(r"\bsum\(orders\)", joined)


def test_there_are_refusal_cases_for_every_layer_that_matters():
    keys = {case.key for case in questions.MUST_REFUSE}
    assert {"refresh_tokens", "own_audit_trail", "identities", "marts_without_tenant_filter", "write", "second_statement", "comment_smuggling"} <= keys


@pytest.mark.parametrize("case", questions.MUST_REFUSE, ids=lambda c: c.key)
def test_forbidden_queries_are_refused(case):
    with pytest.raises(sql_guard.UnsafeSql):
        sql_guard.validate(case.sql)


@pytest.mark.parametrize("case", questions.MUST_REFUSE, ids=lambda c: c.key)
def test_refusals_say_something_specific(case):
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
    safe = sql_guard.validate("select cost from copilot.mart_ppc_campaign_daily where campaign_name = 'Update Bundle' limit 5")
    assert "Update Bundle" in safe


def test_the_runner_contains_no_write_statement():
    lowered = RUNNER_SOURCE.lower()
    for pattern in (r"insert\s+into", r"update\s+\w+\s+set", r"delete\s+from"):
        assert not re.search(pattern, lowered), f"write statement in runner: {pattern}"


def test_rows_returned_to_a_model_are_bounded():
    assert 0 < runner.MAX_ROWS <= 5000


def test_a_proposal_cannot_be_made_at_answer_tier():
    req = audit.CopilotRequest(tenant_id="11111111-1111-1111-1111-111111111111", actor_user_id=None, question="should I raise this bid?", tier=audit.TIER_ANSWER)
    answer = runner.Answer(columns=["acos"], rows=[(0.24,)], sql="select 1 limit 1")
    with pytest.raises(runner.CopilotRefusal):
        runner.propose(req, answer, "raise the bid to 1.20")


def test_a_proposal_never_applies_itself():
    req = audit.CopilotRequest(tenant_id="11111111-1111-1111-1111-111111111111", actor_user_id=None, question="what would you change?", tier=audit.TIER_PROPOSE)
    answer = runner.Answer(columns=["acos"], rows=[(0.24,)], sql="select 1 limit 1")
    proposal = runner.propose(req, answer, "raise the budget to 24")
    assert proposal["applies_automatically"] is False
    assert "approval queue" in proposal["how_to_apply"]


def test_an_empty_answer_is_not_a_failure():
    answer = runner.Answer(columns=["keyword_text"], rows=[], sql="select 1 limit 1")
    assert answer.is_empty
    assert answer.row_count == 0


def test_a_request_must_name_a_tenant():
    with pytest.raises(ValueError):
        audit.CopilotRequest(tenant_id="", actor_user_id=None, question="anything")


def test_an_unknown_tier_is_refused():
    with pytest.raises(ValueError):
        audit.CopilotRequest(tenant_id="11111111-1111-1111-1111-111111111111", actor_user_id=None, question="anything", tier="T9")


@pytest.mark.parametrize("secret", ["Atzr|IQEBLjAsAhRmHjNgHpi0U-Dme37rR6CuUpSR", "Atza|IQEBLjAsAhRmHjNgHpi0U-Dme37rR6CuUpSR", "postgresql://axaty:hunter2@db:5432/axaty", "amzn1.application-oa2-client.abc123def456", "sk-abcdefghijklmnopqrstuvwx"])
def test_credentials_pasted_into_a_question_are_redacted(secret):
    cleaned = audit.redact(f"why is this failing? {secret}")
    assert secret not in cleaned
    assert "redacted" in cleaned


def test_redaction_leaves_ordinary_questions_alone():
    question = "why did ACOS jump on Hook Tape Exact last week?"
    assert audit.redact(question) == question


def test_audit_refuses_to_write_as_the_copilot_itself(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_APP", "postgresql://same:same@localhost/axaty")
    monkeypatch.setenv("DATABASE_URL_COPILOT", "postgresql://same:same@localhost/axaty")
    with pytest.raises(audit.AuditMisconfigured):
        audit.audit_connection_string()


def test_audit_needs_an_app_connection(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_APP", raising=False)
    with pytest.raises(audit.AuditMisconfigured):
        audit.audit_connection_string()


def test_refusals_and_errors_are_separate_actions():
    assert audit.ACTION_REFUSED != audit.ACTION_ERROR
    assert issubclass(runner.CopilotRefusal, Exception)
    assert not issubclass(runner.CopilotRefusal, runner.CopilotError)
