"""Provider adapters: request shape in, response shape out. Nothing else (#35).

Each adapter knows two things — how to build a request and how to read a reply.
Retries, budget, redaction, fallback and logging all live in gateway.py, because
five copies of safety logic means the newest provider is always the least safe
one, and the newest provider is the one added in a hurry.

Providers here:

  openrouter  default; one key, many models
  openai      chat completions
  anthropic   messages API
  gemini      generateContent
  ollama      local, no key, no network egress

Ollama matters more than it looks. Some clients will not allow their sales and
margin data to leave their own machine for any third-party API, and for those
clients every other provider is a non-starter no matter how good it is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable


class UnknownProvider(KeyError):
    """Raised instead of quietly falling back to a default.

    A typo in LLM_PROVIDER that resolved to 'openrouter' would send a tenant's
    data to a provider they did not choose. That is a consent problem, not a
    configuration problem.
    """


class ProviderMisconfigured(RuntimeError):
    """Key missing, or a local provider pointed at a remote host."""


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None
    completion_tokens: int | None

    @property
    def total(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Usage
    model: str
    raw_finish_reason: str | None = None

    @property
    def was_truncated(self) -> bool:
        """A reply cut off at the token ceiling.

        Worth surfacing: a truncated answer reads as a complete one. Half a
        recommendation is the kind of confident-looking wrongness this codebase
        keeps paying for.
        """
        return self.raw_finish_reason in {"length", "max_tokens", "MAX_TOKENS"}


@dataclass(frozen=True)
class Request:
    """What the gateway hands an adapter. Provider-neutral on purpose."""

    model: str
    system: str
    user: str
    max_output_tokens: int = 1024
    temperature: float = 0.0  # analytics, not prose: same question, same answer


@dataclass(frozen=True)
class HttpCall:
    """A fully built HTTP request. The gateway sends it; the adapter never does.

    Separating build from send is what makes every adapter testable with no
    network and no key: assert on the dict.
    """

    method: str
    url: str
    headers: dict[str, str]
    json: dict[str, Any]


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    default_model: str
    api_key_env: str | None
    base_url_env: str
    default_base_url: str
    build: Callable[["Provider", Request, str | None], HttpCall]
    parse: Callable[[dict[str, Any]], Completion]
    is_local: bool = False
    notes: str = ""
    # Price per 1M tokens (input, output), by model. See PRICED_ON below.
    prices: dict[str, tuple[float, float]] = field(default_factory=dict)

    def base_url(self) -> str:
        return os.environ.get(self.base_url_env) or self.default_base_url

    def api_key(self) -> str | None:
        if self.api_key_env is None:
            return None
        return os.environ.get(self.api_key_env) or None

    def require_key(self) -> str | None:
        """Fail before dispatch, not on a 401 after it."""
        if self.api_key_env is None:
            return None
        key = self.api_key()
        if not key:
            raise ProviderMisconfigured(
                f"{self.key}: {self.api_key_env} is not set. "
                "Keys belong in the token vault, encrypted with the KEK — the same "
                "treatment as Amazon refresh tokens."
            )
        return key


# --- pricing --------------------------------------------------------------
#
# USD per 1M tokens, (input, output). Pinned with a date because these change
# and a stale price table that looks authoritative is worse than an obviously
# old one. A model missing from here is UNPRICED, which is not the same as free:
# see price_for().

PRICED_ON = "2026-08-24"
PRICE_SOURCE = "provider public pricing pages; verify before quoting a client"


def _openrouter_build(p: Provider, r: Request, key: str | None) -> HttpCall:
    return HttpCall(
        method="POST",
        url=f"{p.base_url().rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # OpenRouter attributes traffic by these; harmless elsewhere.
            "HTTP-Referer": os.environ.get("LLM_APP_URL", "http://localhost:3000"),
            "X-Title": "AXATY Command Center",
        },
        json={
            "model": r.model,
            "messages": [
                {"role": "system", "content": r.system},
                {"role": "user", "content": r.user},
            ],
            "max_tokens": r.max_output_tokens,
            "temperature": r.temperature,
        },
    )


def _openai_compatible_parse(body: dict[str, Any]) -> Completion:
    choices = body.get("choices") or []
    if not choices:
        raise ValueError(f"no choices in response: {sorted(body)}")
    message = choices[0].get("message") or {}
    usage = body.get("usage") or {}
    return Completion(
        text=message.get("content") or "",
        usage=Usage(
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        ),
        model=body.get("model") or "",
        raw_finish_reason=choices[0].get("finish_reason"),
    )


def _openai_build(p: Provider, r: Request, key: str | None) -> HttpCall:
    return HttpCall(
        method="POST",
        url=f"{p.base_url().rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": r.model,
            "messages": [
                {"role": "system", "content": r.system},
                {"role": "user", "content": r.user},
            ],
            "max_tokens": r.max_output_tokens,
            "temperature": r.temperature,
        },
    )


def _anthropic_build(p: Provider, r: Request, key: str | None) -> HttpCall:
    return HttpCall(
        method="POST",
        url=f"{p.base_url().rstrip('/')}/v1/messages",
        headers={
            "x-api-key": key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": r.model,
            # Anthropic takes the system prompt as its own field, not a message.
            "system": r.system,
            "messages": [{"role": "user", "content": r.user}],
            "max_tokens": r.max_output_tokens,
            "temperature": r.temperature,
        },
    )


def _anthropic_parse(body: dict[str, Any]) -> Completion:
    blocks = body.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    usage = body.get("usage") or {}
    return Completion(
        text=text,
        usage=Usage(
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
        ),
        model=body.get("model") or "",
        raw_finish_reason=body.get("stop_reason"),
    )


def _gemini_build(p: Provider, r: Request, key: str | None) -> HttpCall:
    # Gemini authenticates with a query parameter. The gateway must never log a
    # full URL for this provider; redact() covers the key pattern either way.
    url = f"{p.base_url().rstrip('/')}/v1beta/models/{r.model}:generateContent?key={key}"
    return HttpCall(
        method="POST",
        url=url,
        headers={"Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": r.system}]},
            "contents": [{"role": "user", "parts": [{"text": r.user}]}],
            "generationConfig": {
                "maxOutputTokens": r.max_output_tokens,
                "temperature": r.temperature,
            },
        },
    )


def _gemini_parse(body: dict[str, Any]) -> Completion:
    candidates = body.get("candidates") or []
    text = ""
    finish = None
    if candidates:
        finish = candidates[0].get("finishReason")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
    meta = body.get("usageMetadata") or {}
    return Completion(
        text=text,
        usage=Usage(
            prompt_tokens=meta.get("promptTokenCount"),
            completion_tokens=meta.get("candidatesTokenCount"),
        ),
        model=body.get("modelVersion") or "",
        raw_finish_reason=finish,
    )


def _ollama_build(p: Provider, r: Request, key: str | None) -> HttpCall:
    return HttpCall(
        method="POST",
        url=f"{p.base_url().rstrip('/')}/api/chat",
        headers={"Content-Type": "application/json"},
        json={
            "model": r.model,
            "messages": [
                {"role": "system", "content": r.system},
                {"role": "user", "content": r.user},
            ],
            "stream": False,
            "options": {
                "temperature": r.temperature,
                "num_predict": r.max_output_tokens,
            },
        },
    )


def _ollama_parse(body: dict[str, Any]) -> Completion:
    return Completion(
        text=(body.get("message") or {}).get("content") or "",
        usage=Usage(
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
        ),
        model=body.get("model") or "",
        raw_finish_reason=body.get("done_reason"),
    )


PROVIDERS: dict[str, Provider] = {
    "openrouter": Provider(
        key="openrouter",
        label="OpenRouter",
        default_model="google/gemini-2.0-flash-001",
        api_key_env="OPENROUTER_API_KEY",
        base_url_env="OPENROUTER_BASE_URL",
        default_base_url="https://openrouter.ai/api/v1",
        build=_openrouter_build,
        parse=_openai_compatible_parse,
        notes="Default. One key, many models; model swap needs no new adapter.",
        prices={
            "google/gemini-2.0-flash-001": (0.10, 0.40),
            "openai/gpt-4o-mini": (0.15, 0.60),
            "anthropic/claude-3.5-sonnet": (3.00, 15.00),
        },
    ),
    "openai": Provider(
        key="openai",
        label="OpenAI",
        default_model="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        default_base_url="https://api.openai.com/v1",
        build=_openai_build,
        parse=_openai_compatible_parse,
        prices={"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00)},
    ),
    "anthropic": Provider(
        key="anthropic",
        label="Anthropic",
        default_model="claude-3-5-sonnet-latest",
        api_key_env="ANTHROPIC_API_KEY",
        base_url_env="ANTHROPIC_BASE_URL",
        default_base_url="https://api.anthropic.com",
        build=_anthropic_build,
        parse=_anthropic_parse,
        prices={
            "claude-3-5-sonnet-latest": (3.00, 15.00),
            "claude-3-5-haiku-latest": (0.80, 4.00),
        },
    ),
    "gemini": Provider(
        key="gemini",
        label="Google Gemini",
        default_model="gemini-2.0-flash",
        api_key_env="GEMINI_API_KEY",
        base_url_env="GEMINI_BASE_URL",
        default_base_url="https://generativelanguage.googleapis.com",
        build=_gemini_build,
        parse=_gemini_parse,
        notes="Authenticates by query parameter; never log the raw URL.",
        prices={"gemini-2.0-flash": (0.10, 0.40), "gemini-1.5-pro": (1.25, 5.00)},
    ),
    "ollama": Provider(
        key="ollama",
        label="Ollama (local)",
        default_model="llama3.1:8b",
        api_key_env=None,
        base_url_env="OLLAMA_BASE_URL",
        default_base_url="http://localhost:11434",
        build=_ollama_build,
        parse=_ollama_parse,
        is_local=True,
        notes=(
            "For clients who will not send sales or margin data to a third-party "
            "API. Without this option those clients have no product at all."
        ),
        prices={},  # priced at zero by price_for(), not unknown
    ),
}

DEFAULT_PROVIDER = "openrouter"


def provider(key: str) -> Provider:
    try:
        return PROVIDERS[key]
    except KeyError as exc:
        raise UnknownProvider(
            f"unknown provider {key!r}; known: {', '.join(sorted(PROVIDERS))}"
        ) from exc


def configured_provider() -> Provider:
    return provider(os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER))


def price_for(provider_key: str, model: str) -> tuple[float, float] | None:
    """USD per 1M (input, output) tokens, or None when the model is unpriced.

    None, never (0.0, 0.0). Treating an unknown price as free is the most
    expensive default available here: point LLM_MODEL at something the table has
    never heard of and spend becomes invisible while the budget reports room to
    spare. The gateway refuses unpriced models unless told otherwise.

    Local inference is the one honest zero — it costs nothing per token, which is
    a different fact from "we do not know".
    """
    p = provider(provider_key)
    if p.is_local:
        return (0.0, 0.0)
    return p.prices.get(model)


def cost_usd(provider_key: str, model: str, usage: Usage) -> float | None:
    """Cost of one call, or None when it cannot be known."""
    price = price_for(provider_key, model)
    if price is None:
        return None
    per_in, per_out = price
    prompt = usage.prompt_tokens or 0
    completion = usage.completion_tokens or 0
    return round((prompt * per_in + completion * per_out) / 1_000_000, 6)


def default_model_for(provider_key: str) -> str:
    return os.environ.get("LLM_MODEL") or provider(provider_key).default_model


def build_call(provider_key: str, request: Request) -> HttpCall:
    """Build without sending. Keys are read here so a missing key fails early."""
    p = provider(provider_key)
    return p.build(p, request, p.require_key())


def parse_response(provider_key: str, body: dict[str, Any]) -> Completion:
    return provider(provider_key).parse(body)


def local_providers() -> list[str]:
    return sorted(k for k, p in PROVIDERS.items() if p.is_local)


def remote_providers() -> list[str]:
    return sorted(k for k, p in PROVIDERS.items() if not p.is_local)
