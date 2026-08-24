"""The only way to reach a model (#35).

Adapters build requests. This holds every rule: budget, retries, fallback,
redaction, logging. One place, because adding a sixth provider must not be an
opportunity to forget the budget — and it will be, if the budget lives in five
adapters.

Order of operations, and none of it is rearrangeable:

  1. resolve provider and model      (unknown -> raise, never a silent default)
  2. price the model                 (unpriced -> refuse, not "assume free")
  3. read this month's spend         (BEFORE the call)
  4. dispatch, with retries          (429/5xx only)
  5. write one llm_call row per attempt, in a finally block

What is deliberately impossible here:

  * a refusal being retried on another provider — see should_fallback()
  * a 401 being hidden by falling back to a provider that does have a key
  * a prompt reaching the database — llm_call has no column for it, on purpose
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from services.copilot import audit
from services.copilot.llm import providers as pv

# Budget
DEFAULT_MONTHLY_BUDGET_USD = 25.0

# Retries. Small on purpose: a copilot answer has a human waiting for it, and a
# generous retry policy turns one slow provider into a page that never loads.
MAX_ATTEMPTS_PER_PROVIDER = 3
MAX_RETRY_AFTER_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 60.0

# Statuses recorded in llm_call. Must match the CHECK constraint in 0010.
STATUS_SUCCESS = "success"
STATUS_REFUSED = "refused"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"
STATUS_BUDGET = "budget_exceeded"

RETRYABLE_HTTP = frozenset({429, 500, 502, 503, 504, 529})

# A key the provider rejected is a configuration problem. Sending the same
# request to whichever provider does happen to have a working key hides it, and
# spends real money doing so.
NEVER_FALLBACK_HTTP = frozenset({400, 401, 403, 404, 422})


class LlmError(RuntimeError):
    """Something went wrong."""


class LlmRefusal(Exception):
    """The model, or we, declined.

    Deliberately NOT a subclass of LlmError, exactly as CopilotRefusal is not a
    subclass of CopilotError. If a refusal were an error, generic error handling
    would retry it, and retrying a refusal until something complies is the one
    behaviour this gateway exists to prevent.
    """


class BudgetExceeded(LlmRefusal):
    """A refusal, not an error: the system worked. It also must not be retried."""


class Unpriced(LlmRefusal):
    """The model has no known price, so the budget cannot mean anything."""


class ProviderUnavailable(LlmError):
    """Retries and fallbacks are exhausted."""


@dataclass(frozen=True)
class Budget:
    monthly_usd: float

    @classmethod
    def from_env(cls) -> "Budget":
        raw = os.environ.get("LLM_MONTHLY_BUDGET")
        if raw is None or raw.strip() == "":
            return cls(DEFAULT_MONTHLY_BUDGET_USD)
        try:
            value = float(raw)
        except ValueError as exc:
            # Not a warning. An unparseable ceiling that degraded to "unlimited"
            # would be discovered by an invoice.
            raise LlmError(f"LLM_MONTHLY_BUDGET is not a number: {raw!r}") from exc
        if value < 0:
            raise LlmError("LLM_MONTHLY_BUDGET cannot be negative")
        return cls(value)

    @property
    def is_disabled(self) -> bool:
        """Zero means no LLM calls, not unlimited.

        The opposite reading is the kind of default that empties an account.
        """
        return self.monthly_usd == 0


@dataclass
class Attempt:
    """One row of llm_call, assembled as the attempt happens."""

    tenant_id: str
    purpose: str
    provider: str
    model: str
    status: str = STATUS_ERROR
    attempt: int = 1
    fallback_from: str | None = None
    request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    error: str | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


@dataclass
class Result:
    text: str
    provider: str
    model: str
    cost_usd: float | None
    total_tokens: int | None
    latency_ms: int
    attempts: list[Attempt] = field(default_factory=list)
    truncated: bool = False

    @property
    def fell_back(self) -> bool:
        return len({a.provider for a in self.attempts}) > 1


# --- database -------------------------------------------------------------
#
# Written as the app role over DATABASE_URL_APP, the same connection audit.py
# uses. The copilot role is read-only and has no grant on llm_call (0010), which
# is correct: a component should not be able to edit the record of what it spent.


def connection_string() -> str:
    url = os.environ.get("DATABASE_URL_APP")
    if not url:
        raise LlmError(
            "DATABASE_URL_APP is not set. Every LLM call is logged before it is "
            "billed; without the log there is no budget."
        )
    return url


def spend_this_month(tenant_id: str) -> float:
    """USD spent this calendar month by this tenant.

    Reads the view from 0010 so "this month" is defined in one place. Note the
    view counts failed and refused attempts too: a provider that charges for a
    refusal still charged.
    """
    import psycopg

    with psycopg.connect(connection_string()) as conn, conn.cursor() as cur:
        cur.execute("select set_tenant(%s)", (tenant_id,))
        cur.execute(
            "select coalesce(sum(spend), 0) from v_llm_spend_this_month where tenant_id = %s",
            (tenant_id,),
        )
        row = cur.fetchone()
        conn.commit()
    return float(row[0]) if row and row[0] is not None else 0.0


def record(attempt: Attempt) -> None:
    """Insert one llm_call row. Never raises into the caller's path.

    Deliberately different from audit.py, where a failed write refuses the
    request. There, the write IS the accountability. Here the model call may have
    already happened and already cost money; throwing away a usable answer
    because the meter could not be read would be the wrong trade. The failure is
    surfaced loudly instead.
    """
    import psycopg

    sql = """
        insert into llm_call (
            tenant_id, request_id, purpose, provider, model, status, attempt,
            fallback_from, prompt_tokens, completion_tokens, total_tokens,
            cost_usd, latency_ms, error, finished_at
        ) values (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, now()
        )
    """
    try:
        with psycopg.connect(connection_string()) as conn, conn.cursor() as cur:
            cur.execute("select set_tenant(%s)", (attempt.tenant_id,))
            cur.execute(
                sql,
                (
                    attempt.tenant_id,
                    attempt.request_id,
                    attempt.purpose,
                    attempt.provider,
                    attempt.model,
                    attempt.status,
                    attempt.attempt,
                    attempt.fallback_from,
                    attempt.prompt_tokens,
                    attempt.completion_tokens,
                    attempt.total_tokens,
                    attempt.cost_usd,
                    attempt.latency_ms,
                    audit.redact(attempt.error) if attempt.error else None,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(f"[llm] FAILED TO RECORD CALL: {exc}. Spend is now under-counted.")


# --- policy ---------------------------------------------------------------


def fallback_chain(primary: str) -> list[str]:
    """Providers to try, in order. Primary first, never duplicated.

    A local provider is never appended automatically. Sending a tenant's data to
    a remote provider because the local one was busy would reverse the exact
    decision that made them choose local.
    """
    chain = [primary]
    raw = os.environ.get("LLM_FALLBACK_PROVIDERS", "")
    for key in (part.strip() for part in raw.split(",")):
        if not key or key in chain:
            continue
        pv.provider(key)  # raises UnknownProvider on a typo, rather than skipping
        chain.append(key)
    if pv.provider(primary).is_local and len(chain) > 1:
        raise LlmError(
            f"{primary} is local but LLM_FALLBACK_PROVIDERS names remote providers. "
            "A client who chose local inference did not agree to a remote fallback."
        )
    return chain


def should_fallback(status_code: int | None, exc: BaseException | None) -> bool:
    """Whether to try the next provider.

    The refusal case is the whole point of this function. A refused request that
    gets passed along until something complies is worse than no gateway at all,
    and 0010's llm_call_refusal_is_never_shopped constraint means the attempt
    could not even be recorded.
    """
    if isinstance(exc, LlmRefusal):
        return False
    if status_code is None:
        return True  # network-level failure: another provider is a fair try
    if status_code in NEVER_FALLBACK_HTTP:
        return False
    return status_code in RETRYABLE_HTTP or status_code >= 500


def retry_delay(attempt: int, retry_after: str | None) -> float:
    """Honour Retry-After when the provider sends one; back off otherwise."""
    if retry_after:
        try:
            return min(float(retry_after), MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            pass
    return min(2.0**attempt, MAX_RETRY_AFTER_SECONDS)


def check_budget(tenant_id: str, budget: Budget, estimated: float) -> float:
    """Called BEFORE dispatch. Returns spend so far.

    Afterwards would be reporting, not enforcement: the money is already gone by
    the time the number is correct.
    """
    if budget.is_disabled:
        raise BudgetExceeded(
            "LLM_MONTHLY_BUDGET is 0, so model calls are switched off. "
            "Set a positive ceiling to enable them."
        )
    spent = spend_this_month(tenant_id)
    if spent + estimated > budget.monthly_usd:
        raise BudgetExceeded(
            f"this month's LLM spend is ${spent:.4f} and this call would add about "
            f"${estimated:.4f}, over the ${budget.monthly_usd:.2f} ceiling. "
            "Raise LLM_MONTHLY_BUDGET or wait for the month to roll over."
        )
    return spent


def estimate_cost(provider_key: str, model: str, request: pv.Request) -> float:
    """Rough pre-flight cost, in USD.

    Four characters per token, and output assumed to use its full ceiling. The
    estimate is deliberately pessimistic: an optimistic one lets the last call of
    the month sail past the ceiling, and the whole point is to stop before the
    spend, not to be accurate about it afterwards.
    """
    price = pv.price_for(provider_key, model)
    if price is None:
        raise Unpriced(
            f"{provider_key}/{model} has no known price, so this call cannot be "
            "counted against the budget. Add it to providers.PRICES, or set "
            "LLM_ALLOW_UNPRICED=true to accept untracked spend."
        )
    per_in, per_out = price
    prompt_tokens = (len(request.system) + len(request.user)) / 4
    return round(
        (prompt_tokens * per_in + request.max_output_tokens * per_out) / 1_000_000, 6
    )


def allow_unpriced() -> bool:
    return os.environ.get("LLM_ALLOW_UNPRICED", "").lower() in {"1", "true", "yes"}


# --- dispatch -------------------------------------------------------------


def _send(call: pv.HttpCall) -> tuple[int, dict[str, Any], dict[str, str]]:
    import httpx

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.request(
            call.method, call.url, headers=call.headers, json=call.json
        )
    body: dict[str, Any]
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - provider returned HTML or nothing
        body = {"error": response.text[:500]}
    return response.status_code, body, dict(response.headers)


def call(
    tenant_id: str,
    purpose: str,
    request: pv.Request | None = None,
    *,
    system: str = "",
    user: str = "",
    request_id: str | None = None,
    provider_key: str | None = None,
    budget: Budget | None = None,
) -> Result:
    """Send one request, with retries and fallback. The only entry point."""
    if not tenant_id:
        raise LlmError("tenant_id is required: spend is per tenant, always")
    if not purpose:
        raise LlmError("purpose is required: an unlabelled call cannot be explained later")

    budget = budget or Budget.from_env()
    primary = provider_key or pv.configured_provider().key
    chain = fallback_chain(primary)
    request_id = request_id or str(uuid.uuid4())

    if request is None:
        request = pv.Request(model=pv.default_model_for(primary), system=system, user=user)

    attempts: list[Attempt] = []
    last_error: BaseException | None = None

    for index, key in enumerate(chain):
        model = request.model if index == 0 else pv.default_model_for(key)
        active = pv.Request(
            model=model,
            system=request.system,
            user=request.user,
            max_output_tokens=request.max_output_tokens,
            temperature=request.temperature,
        )

        try:
            estimated = estimate_cost(key, model, active)
        except Unpriced:
            if not allow_unpriced():
                raise
            estimated = 0.0

        # Budget is checked once per provider, because a fallback is another call
        # and another charge.
        check_budget(tenant_id, budget, estimated)

        for attempt_no in range(1, MAX_ATTEMPTS_PER_PROVIDER + 1):
            row = Attempt(
                tenant_id=tenant_id,
                purpose=purpose,
                provider=key,
                model=model,
                attempt=attempt_no,
                request_id=request_id,
                fallback_from=chain[index - 1] if index > 0 else None,
            )
            started = time.monotonic()
            status_code: int | None = None
            try:
                http_call = pv.build_call(key, active)
                status_code, body, headers = _send(http_call)
                row.latency_ms = int((time.monotonic() - started) * 1000)

                if status_code >= 400:
                    row.status = (
                        STATUS_TIMEOUT if status_code in {408, 504} else STATUS_ERROR
                    )
                    row.error = f"HTTP {status_code}: {str(body)[:400]}"
                    if status_code in RETRYABLE_HTTP and attempt_no < MAX_ATTEMPTS_PER_PROVIDER:
                        time.sleep(retry_delay(attempt_no, headers.get("retry-after")))
                        continue
                    last_error = ProviderUnavailable(row.error)
                    if should_fallback(status_code, None):
                        break
                    raise last_error

                completion = pv.parse_response(key, body)
                row.status = STATUS_SUCCESS
                row.prompt_tokens = completion.usage.prompt_tokens
                row.completion_tokens = completion.usage.completion_tokens
                row.cost_usd = pv.cost_usd(key, model, completion.usage)
                attempts.append(row)

                return Result(
                    text=completion.text,
                    provider=key,
                    model=completion.model or model,
                    cost_usd=row.cost_usd,
                    total_tokens=row.total_tokens,
                    latency_ms=row.latency_ms or 0,
                    attempts=list(attempts),
                    truncated=completion.was_truncated,
                )

            except LlmRefusal:
                # Never recorded with fallback_from, never retried elsewhere.
                row.status = STATUS_REFUSED
                row.fallback_from = None
                raise
            except Exception as exc:  # noqa: BLE001
                row.latency_ms = row.latency_ms or int((time.monotonic() - started) * 1000)
                row.status = STATUS_ERROR
                row.error = f"{type(exc).__name__}: {exc}"
                last_error = exc
                if attempt_no < MAX_ATTEMPTS_PER_PROVIDER and should_fallback(None, exc):
                    time.sleep(retry_delay(attempt_no, None))
                    continue
                break
            finally:
                # Always. A crashed call still consumed tokens, and a budget fed
                # only by successes under-counts exactly when it matters most.
                if row.status != STATUS_SUCCESS:
                    attempts.append(row)
                    record(row)

    raise ProviderUnavailable(
        f"all providers failed ({', '.join(chain)}); last error: {last_error}"
    )
