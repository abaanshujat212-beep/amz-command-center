"""LLM gateway and provider adapters (#35). No network, no database, no keys.

Split deliberately: everything here runs on a laptop with nothing provisioned,
because a test that needs infrastructure is a test that does not run. The one
thing that genuinely needs a live provider is a real completion, and that is not
a unit test.

The interesting assertions are all negative — what the gateway refuses to do —
since those are the behaviours nobody notices working correctly.
"""

import re
from pathlib import Path

import pytest

from services.copilot.llm import gateway as gw
from services.copilot.llm import providers as pv

REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / "packages" / "db" / "migrations" / "0010_llm_call.sql"


# --- providers ------------------------------------------------------------


def test_five_providers_and_only_ollama_is_local():
    assert set(pv.PROVIDERS) == {"openrouter", "openai", "anthropic", "gemini", "ollama"}
    assert pv.local_providers() == ["ollama"]
    assert pv.provider("ollama").api_key_env is None


def test_an_unknown_provider_raises_instead_of_defaulting():
    """A typo resolving to the default would send tenant data to a provider the
    tenant never chose. That is consent, not configuration."""
    with pytest.raises(pv.UnknownProvider) as exc:
        pv.provider("openroutr")
    assert "openrouter" in str(exc.value)  # names the real options


def test_a_missing_key_fails_before_dispatch(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(pv.ProviderMisconfigured) as exc:
        pv.provider("openai").require_key()
    assert "OPENAI_API_KEY" in str(exc.value)


def test_local_provider_needs_no_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert pv.provider("ollama").require_key() is None
    assert pv.provider("ollama").base_url() == "http://localhost:11434"


@pytest.fixture
def request_obj():
    return pv.Request(model="m", system="you are careful", user="what is our ACOS?")


def test_openai_shaped_request(monkeypatch, request_obj):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    call = pv.build_call("openai", request_obj)
    assert call.url.endswith("/chat/completions")
    assert call.headers["Authorization"] == "Bearer sk-test"
    assert [m["role"] for m in call.json["messages"]] == ["system", "user"]
    assert call.json["temperature"] == 0.0, "analytics must be reproducible"


def test_anthropic_keeps_system_out_of_messages(monkeypatch, request_obj):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    call = pv.build_call("anthropic", request_obj)
    assert call.url.endswith("/v1/messages")
    assert call.headers["x-api-key"] == "sk-ant-test"
    assert call.headers["anthropic-version"] == "2023-06-01"
    assert call.json["system"] == "you are careful"
    assert [m["role"] for m in call.json["messages"]] == ["user"]


def test_gemini_authenticates_in_the_query_string(monkeypatch, request_obj):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaTEST")
    call = pv.build_call("gemini", request_obj)
    assert ":generateContent?key=AIzaTEST" in call.url
    assert "Authorization" not in call.headers
    assert call.json["systemInstruction"]["parts"][0]["text"] == "you are careful"


def test_ollama_sends_no_credentials_anywhere(monkeypatch, request_obj):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    call = pv.build_call("ollama", request_obj)
    assert call.url == "http://localhost:11434/api/chat"
    assert call.json["stream"] is False, "the gateway parses one JSON body, not a stream"
    joined = " ".join(call.headers).lower()
    assert "authorization" not in joined and "api-key" not in joined


# --- response parsing -----------------------------------------------------


def test_openai_usage_mapping():
    c = pv.parse_response(
        "openai",
        {
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )
    assert (c.text, c.usage.total, c.was_truncated) == ("hi", 15, False)


def test_anthropic_usage_mapping():
    """input_tokens/output_tokens, not prompt/completion. Mapped once, here."""
    c = pv.parse_response(
        "anthropic",
        {
            "model": "claude-3-5-sonnet-latest",
            "content": [{"type": "text", "text": "hello"}],
            "usage": {"input_tokens": 7, "output_tokens": 3},
            "stop_reason": "end_turn",
        },
    )
    assert (c.text, c.usage.prompt_tokens, c.usage.completion_tokens) == ("hello", 7, 3)


def test_gemini_usage_mapping():
    c = pv.parse_response(
        "gemini",
        {
            "candidates": [
                {"content": {"parts": [{"text": "a"}, {"text": "b"}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 6},
        },
    )
    assert (c.text, c.usage.total) == ("ab", 10)


def test_ollama_usage_mapping():
    c = pv.parse_response(
        "ollama",
        {
            "model": "llama3.1:8b",
            "message": {"content": "local"},
            "prompt_eval_count": 20,
            "eval_count": 8,
        },
    )
    assert (c.text, c.usage.total) == ("local", 28)


@pytest.mark.parametrize("reason", ["length", "max_tokens", "MAX_TOKENS"])
def test_a_truncated_reply_is_flagged(reason):
    """Half a recommendation reads exactly like a whole one."""
    c = pv.Completion(text="...", usage=pv.Usage(1, 1), model="m", raw_finish_reason=reason)
    assert c.was_truncated


def test_missing_usage_is_none_not_zero():
    """Zero tokens is a claim; unknown is the truth. Zero would silently
    under-count spend."""
    c = pv.parse_response("openai", {"choices": [{"message": {"content": "x"}}]})
    assert c.usage.total is None


# --- pricing --------------------------------------------------------------


def test_an_unpriced_model_is_none_and_never_zero():
    assert pv.price_for("openai", "gpt-9-imaginary") is None
    assert pv.cost_usd("openai", "gpt-9-imaginary", pv.Usage(1000, 1000)) is None


def test_local_inference_is_an_honest_zero():
    assert pv.price_for("ollama", "llama3.1:8b") == (0.0, 0.0)
    assert pv.cost_usd("ollama", "llama3.1:8b", pv.Usage(100_000, 100_000)) == 0.0


def test_cost_arithmetic():
    # 1M input tokens at $0.15/M, 1M output at $0.60/M
    assert pv.cost_usd("openai", "gpt-4o-mini", pv.Usage(1_000_000, 1_000_000)) == 0.75


def test_price_table_says_when_it_was_pinned():
    """A stale price table should look stale, not authoritative."""
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", pv.PRICED_ON)
    assert pv.PRICE_SOURCE


# --- budget ---------------------------------------------------------------


def test_budget_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("LLM_MONTHLY_BUDGET", raising=False)
    assert gw.Budget.from_env().monthly_usd == gw.DEFAULT_MONTHLY_BUDGET_USD


def test_an_unparseable_budget_raises_instead_of_becoming_unlimited(monkeypatch):
    monkeypatch.setenv("LLM_MONTHLY_BUDGET", "twenty five")
    with pytest.raises(gw.LlmError):
        gw.Budget.from_env()


def test_zero_budget_means_off_not_infinite(monkeypatch):
    monkeypatch.setenv("LLM_MONTHLY_BUDGET", "0")
    budget = gw.Budget.from_env()
    assert budget.is_disabled
    with pytest.raises(gw.BudgetExceeded):
        gw.check_budget("t", budget, 0.0)


def test_budget_is_checked_against_spend_before_the_call(monkeypatch):
    monkeypatch.setattr(gw, "spend_this_month", lambda tenant: 24.99)
    with pytest.raises(gw.BudgetExceeded) as exc:
        gw.check_budget("t", gw.Budget(25.0), 0.05)
    assert "24.99" in str(exc.value) and "25.00" in str(exc.value)


def test_a_call_inside_the_ceiling_passes(monkeypatch):
    monkeypatch.setattr(gw, "spend_this_month", lambda tenant: 1.0)
    assert gw.check_budget("t", gw.Budget(25.0), 0.01) == 1.0


def test_estimate_refuses_an_unpriced_model():
    req = pv.Request(model="gpt-9-imaginary", system="s", user="u")
    with pytest.raises(gw.Unpriced) as exc:
        gw.estimate_cost("openai", "gpt-9-imaginary", req)
    assert "LLM_ALLOW_UNPRICED" in str(exc.value), "the escape hatch must be named"


def test_the_estimate_is_pessimistic():
    """Output is assumed to fill its ceiling. An optimistic estimate lets the
    last call of the month sail past the budget."""
    req = pv.Request(model="gpt-4o-mini", system="", user="", max_output_tokens=1_000_000)
    assert gw.estimate_cost("openai", "gpt-4o-mini", req) == pytest.approx(0.60)


# --- the rules that must not bend ----------------------------------------


def test_a_refusal_is_never_shopped_to_another_provider():
    assert gw.should_fallback(None, gw.LlmRefusal("declined")) is False
    assert gw.should_fallback(429, gw.LlmRefusal("declined")) is False


def test_a_budget_refusal_is_also_never_retried():
    assert gw.should_fallback(None, gw.BudgetExceeded("over")) is False


def test_a_refusal_is_not_an_error_so_generic_retries_cannot_catch_it():
    """If BudgetExceeded were an LlmError, one `except LlmError: retry` would turn
    a spending ceiling into a rate limiter."""
    assert not issubclass(gw.LlmRefusal, gw.LlmError)
    assert not issubclass(gw.BudgetExceeded, gw.LlmError)
    assert issubclass(gw.BudgetExceeded, gw.LlmRefusal)
    assert issubclass(gw.Unpriced, gw.LlmRefusal)


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_a_rejected_key_is_surfaced_not_hidden_by_a_fallback(code):
    assert gw.should_fallback(code, None) is False


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504, 529])
def test_overload_falls_back(code):
    assert gw.should_fallback(code, None) is True


def test_a_network_failure_falls_back():
    assert gw.should_fallback(None, TimeoutError("connect")) is True


def test_retry_after_is_honoured_and_capped():
    assert gw.retry_delay(1, "5") == 5.0
    assert gw.retry_delay(1, "99999") == gw.MAX_RETRY_AFTER_SECONDS
    assert gw.retry_delay(1, "soon") == 2.0  # garbage header ignored, not crashed
    assert gw.retry_delay(9, None) == gw.MAX_RETRY_AFTER_SECONDS


def test_fallback_chain_is_just_the_primary_by_default(monkeypatch):
    monkeypatch.delenv("LLM_FALLBACK_PROVIDERS", raising=False)
    assert gw.fallback_chain("openrouter") == ["openrouter"]


def test_fallback_chain_dedupes_and_keeps_order(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "openrouter, gemini ,openai,gemini")
    assert gw.fallback_chain("openrouter") == ["openrouter", "gemini", "openai"]


def test_a_typo_in_the_fallback_list_raises(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "gemni")
    with pytest.raises(pv.UnknownProvider):
        gw.fallback_chain("openrouter")


def test_local_primary_refuses_remote_fallbacks(monkeypatch):
    """A client who chose local inference did not agree to a remote retry when
    the local box was busy. That would reverse the only decision they made."""
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "openrouter")
    with pytest.raises(gw.LlmError) as exc:
        gw.fallback_chain("ollama")
    assert "local" in str(exc.value)


def test_the_gateway_requires_a_tenant_and_a_purpose():
    with pytest.raises(gw.LlmError):
        gw.call("", "copilot_answer", user="hi")
    with pytest.raises(gw.LlmError):
        gw.call("tenant-1", "", user="hi")


def test_logging_needs_the_app_role(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_APP", raising=False)
    with pytest.raises(gw.LlmError) as exc:
        gw.connection_string()
    assert "DATABASE_URL_APP" in str(exc.value)


# --- the Python constants against the SQL --------------------------------
#
# Three copies of Amazon's rate limits were found drifting last week. This is the
# same failure waiting to happen between a migration and the module writing to
# it, so it is pinned rather than trusted.


@pytest.fixture(scope="module")
def migration_sql():
    assert MIGRATION.exists(), f"missing {MIGRATION}"
    return MIGRATION.read_text()


def test_status_values_match_the_check_constraint(migration_sql):
    match = re.search(r"check \(status in \(([^)]*)\)\)", migration_sql)
    assert match, "0010 must constrain status"
    allowed = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    used = {
        gw.STATUS_SUCCESS,
        gw.STATUS_REFUSED,
        gw.STATUS_ERROR,
        gw.STATUS_TIMEOUT,
        gw.STATUS_BUDGET,
    }
    assert used == allowed


def test_the_refusal_rule_lives_in_the_database_too(migration_sql):
    assert "llm_call_refusal_is_never_shopped" in migration_sql
    assert "status = 'refused' and fallback_from is not null" in migration_sql


def test_a_blocked_call_cannot_record_spend(migration_sql):
    assert "llm_call_blocked_calls_cost_nothing" in migration_sql


def test_llm_call_is_tenant_isolated_and_forced(migration_sql):
    assert "enable row level security" in migration_sql
    assert "force row level security" in migration_sql
    assert "nullif(current_setting('app.tenant_id', true), '')" in migration_sql


def test_the_copilot_gets_no_access_to_its_own_cost_ledger(migration_sql):
    assert "grant select, insert on llm_call to axaty_app" in migration_sql
    assert "axaty_copilot" not in migration_sql


def test_no_prompt_is_ever_stored(migration_sql):
    """Token counts, not text. The prompt carries tenant data and cost accounting
    does not need it."""
    assert "prompt_tokens" in migration_sql
    assert not re.search(r"^\s+prompt\s+text", migration_sql, re.MULTILINE)
    source = (REPO / "services" / "copilot" / "llm" / "gateway.py").read_text()
    insert = source[source.index("insert into llm_call") : source.index(") values")]
    assert "prompt," not in insert and "question" not in insert


def test_the_month_is_defined_once_in_sql(migration_sql):
    assert "create or replace view v_llm_spend_this_month" in migration_sql
    assert "date_trunc('month', now())" in migration_sql
