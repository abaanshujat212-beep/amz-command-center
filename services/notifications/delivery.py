"""Provider-neutral notification delivery state machine.

Adapters are intentionally injected. This module never reads credentials and cannot
turn configuration presence into permission to send.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from string import Template
from typing import Protocol

ALLOWED_CHANNELS = frozenset({"email", "whatsapp", "sms"})
FINAL_STATUSES = frozenset({"DELIVERED", "FAILED", "DEAD_LETTER"})
PLACEHOLDER = re.compile(r"\$\{([a-z][a-z0-9_]*)\}")


@dataclass(frozen=True)
class ApprovedTemplate:
    template_id: str
    channel: str
    subject: str | None
    body: str
    variable_allowlist: frozenset[str]


@dataclass(frozen=True)
class RenderedMessage:
    subject: str | None
    body: str


@dataclass(frozen=True)
class AdapterResult:
    outcome: str
    provider_reference: str | None = None
    provider_status: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    cost_amount: float = 0
    cost_currency: str | None = None


class DeliveryAdapter(Protocol):
    def send(
        self, *, recipient_ref: str, message: RenderedMessage, idempotency_key: str
    ) -> AdapterResult: ...


def render_template(template: ApprovedTemplate, variables: dict[str, object]) -> RenderedMessage:
    """Render only explicitly allowed scalar fields; payload objects never leak wholesale."""
    if template.channel not in ALLOWED_CHANNELS:
        raise ValueError("unsupported external channel")
    required = set(PLACEHOLDER.findall(template.body))
    if template.subject:
        required.update(PLACEHOLDER.findall(template.subject))
    if not required.issubset(template.variable_allowlist):
        raise ValueError("template contains a variable outside its allowlist")
    if not required.issubset(variables):
        raise ValueError("template variable is missing")
    safe: dict[str, str] = {}
    for key in required:
        value = variables[key]
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError("template variables must be scalar")
        safe[key] = str(value)
    return RenderedMessage(
        subject=Template(template.subject).substitute(safe) if template.subject else None,
        body=Template(template.body).substitute(safe),
    )


def retry_at(attempt: int, now: dt.datetime) -> dt.datetime:
    if attempt < 1 or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("retry scheduling requires a positive attempt and aware timestamp")
    # 1m, 5m, 25m, then capped at 6h. Deterministic to make replay/audit exact.
    return now + dt.timedelta(minutes=min(360, 5 ** (attempt - 1)))


def _cell(row, name: str, index: int = 0):
    return row[name] if isinstance(row, dict) else row[index]


def record_attempt(
    conn,
    *,
    tenant_id: str,
    delivery_id: str,
    attempt_number: int,
    max_attempts: int,
    idempotency_key: str,
    result: AdapterResult,
    attempted_at: dt.datetime,
) -> str:
    """Append evidence and advance delivery state atomically; duplicate attempts are safe."""
    if result.outcome not in {"DELIVERED", "RETRYABLE", "FAILED"}:
        raise ValueError("unsupported adapter outcome")
    if result.cost_amount < 0 or (result.cost_amount and not result.cost_currency):
        raise ValueError("positive delivery cost requires currency")
    terminal = result.outcome
    next_attempt = None
    dead_lettered_at = None
    if result.outcome == "RETRYABLE":
        if attempt_number >= max_attempts:
            terminal = "DEAD_LETTER"
            dead_lettered_at = attempted_at
        else:
            next_attempt = retry_at(attempt_number, attempted_at)
    inserted = conn.execute(
        """insert into notification_delivery_attempt
             (tenant_id,delivery_id,attempt_number,idempotency_key,outcome,
              provider_reference,provider_status,error_code,error_detail,
              cost_amount,cost_currency,attempted_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (tenant_id,idempotency_key) do nothing returning id""",
        (
            tenant_id,
            delivery_id,
            attempt_number,
            idempotency_key,
            terminal,
            result.provider_reference,
            result.provider_status,
            result.error_code,
            result.error_detail,
            result.cost_amount,
            result.cost_currency,
            attempted_at,
        ),
    ).fetchone()
    if inserted is None:
        row = conn.execute(
            """select outcome from notification_delivery_attempt
                 where tenant_id=%s and idempotency_key=%s""",
            (tenant_id, idempotency_key),
        ).fetchone()
        if row is None:
            raise RuntimeError("delivery attempt idempotency lookup failed")
        return str(_cell(row, "outcome"))
    conn.execute(
        """update notification_delivery set status=%s,attempt=%s,retry_eligible=%s,
                  next_attempt_at=%s,dead_lettered_at=%s,provider_reference=%s,error=%s,
                  cost_amount=cost_amount+%s,cost_currency=coalesce(%s,cost_currency),
                  delivered_at=case when %s='DELIVERED' then %s else delivered_at end,
                  updated_at=now()
            where tenant_id=%s and id=%s""",
        (
            terminal,
            attempt_number,
            terminal == "RETRYABLE",
            next_attempt,
            dead_lettered_at,
            result.provider_reference,
            result.error_detail,
            result.cost_amount,
            result.cost_currency,
            terminal,
            attempted_at,
            tenant_id,
            delivery_id,
        ),
    )
    return terminal


def accept_verified_callback(
    conn,
    *,
    tenant_id: str,
    delivery_id: str,
    channel: str,
    callback_id: str,
    status: str,
    provider_reference: str | None,
    signature_verified: bool,
) -> bool:
    """Record an already provider-verified callback once; verification stays adapter-owned."""
    if not signature_verified:
        raise ValueError("provider callback signature is not verified")
    if channel not in ALLOWED_CHANNELS or status not in {"DELIVERED", "FAILED", "RETRYABLE"}:
        raise ValueError("invalid provider callback")
    row = conn.execute(
        """insert into notification_callback_event
             (tenant_id,delivery_id,channel,provider_callback_id,delivery_status,
              signature_verified,provider_reference)
           values (%s,%s,%s,%s,%s,true,%s)
           on conflict (tenant_id,channel,provider_callback_id) do nothing returning id""",
        (tenant_id, delivery_id, channel, callback_id, status, provider_reference),
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        """update notification_delivery set status=%s,provider_reference=coalesce(%s,provider_reference),
                  delivered_at=case when %s='DELIVERED' then now() else delivered_at end,
                  retry_eligible=(%s='RETRYABLE'),updated_at=now()
            where tenant_id=%s and id=%s and channel=%s and status <> 'DEAD_LETTER'""",
        (status, provider_reference, status, status, tenant_id, delivery_id, channel),
    )
    return True
