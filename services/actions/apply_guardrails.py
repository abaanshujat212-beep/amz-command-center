"""Fail-closed reconstruction of guardrails immediately before live apply."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from numbers import Real

from services.actions import state_machine as sm
from services.rules import guardrails as gr
from services.rules.evidence import CONTEXT_VERSION


class ApplyGuardrailError(RuntimeError):
    """Current policy or persisted evidence blocks provider access."""


@dataclass(frozen=True)
class ApplyGuardrailResult:
    budget_increase: float = 0.0


def _number(value, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ApplyGuardrailError(f"{name} must be numeric") from exc
    return float(value)


def _date(value, name: str) -> dt.date:
    try:
        return value if isinstance(value, dt.date) else dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ApplyGuardrailError(f"{name} is invalid") from exc


def _datetime(value, name: str) -> dt.datetime:
    try:
        parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ApplyGuardrailError(f"{name} is invalid") from exc
    if parsed.tzinfo is None:
        raise ApplyGuardrailError(f"{name} must include a timezone")
    return parsed


def load_apply_evidence(cur, action: sm.Action) -> dict:
    cur.execute(
        """
        select e.data_through, e.metrics_snapshot,
               coalesce(ch.applied_today, 0) as applied_today,
               coalesce(ch.budget_delta_today, 0) as budget_delta_today,
               last_change.last_applied_at
          from action a
          left join rule_evaluation e
            on e.tenant_id = a.tenant_id and e.id = a.evaluation_id
          left join v_changes_today ch on ch.tenant_id = a.tenant_id
          left join v_last_applied_action last_change
            on last_change.tenant_id = a.tenant_id
           and last_change.entity_type = a.entity_type
           and last_change.entity_id = a.entity_id
         where a.tenant_id = %s and a.id = %s
        """,
        (action.tenant_id, action.id),
    )
    row = cur.fetchone()
    if row is None or row["data_through"] is None or not isinstance(row["metrics_snapshot"], dict):
        raise ApplyGuardrailError("action evaluation evidence is missing")
    return row


def validate_apply_guardrails(
    cur,
    action: sm.Action,
    cfg: gr.TenantGuardConfig,
    *,
    now: dt.datetime,
    projected_changes: int = 0,
    projected_budget_increase: float = 0.0,
) -> ApplyGuardrailResult:
    """Re-run canonical guards; never alter an already approved target."""
    row = load_apply_evidence(cur, action)
    metrics = row["metrics_snapshot"]
    context = metrics.get("guardrail_context")
    if not isinstance(context, dict) or context.get("version") != CONTEXT_VERSION:
        raise ApplyGuardrailError("guardrail_context is missing or unsupported")
    freshness = context.get("source_freshness")
    if not isinstance(freshness, dict) or freshness.get("state") != "fresh":
        raise ApplyGuardrailError("source freshness evidence is missing or not fresh")

    try:
        evaluated = int(context["entities_evaluated"])
        matched = int(context["entities_matched"])
        min_clicks = int(context["min_clicks"])
        min_impressions = int(context["min_impressions"])
        clicks = int(metrics.get("clicks") or 0)
        impressions = int(metrics.get("impressions") or 0)
    except (KeyError, TypeError, ValueError) as exc:
        raise ApplyGuardrailError("guardrail_context contains invalid counts") from exc
    if evaluated < 0 or matched < 0 or matched > evaluated or min_clicks < 0 or min_impressions < 0:
        raise ApplyGuardrailError("guardrail_context contains impossible counts")

    before = _number((action.before_value or {}).get("value"), "before_value")
    after = _number(action.after_value.get("value"), "after_value")
    proposal = gr.Proposal(
        entity_type=action.entity_type,
        entity_id=action.entity_id,
        action_type=action.action_type,
        before_value=before,
        after_value=after,
        clicks=clicks,
        impressions=impressions,
        break_even_acos=_number(metrics.get("break_even_acos"), "break_even_acos"),
    )
    run_context = gr.RunContext(
        now=now,
        data_through=_date(row["data_through"], "data_through"),
        data_loaded_at=_datetime(freshness.get("data_loaded_at"), "data_loaded_at"),
        changes_applied_today=int(row["applied_today"]) + projected_changes,
        budget_increase_today=float(row["budget_delta_today"]) + projected_budget_increase,
        entities_evaluated=evaluated,
        entities_matched=matched,
        last_applied_at=row["last_applied_at"],
    )
    decision = gr.check(proposal, cfg, run_context, min_clicks, min_impressions)
    if not decision.allowed:
        guard = decision.blocked_by.value if decision.blocked_by else "unknown"
        raise ApplyGuardrailError(f"{guard}: {'; '.join(decision.notes)}")
    if decision.clamped or decision.value != after:
        raise ApplyGuardrailError("current guardrails would change the approved target")

    budget_increase = 0.0
    if action.action_type == "set_budget" and before is not None and after is not None:
        budget_increase = max(after - before, 0.0)
    return ApplyGuardrailResult(budget_increase=budget_increase)
