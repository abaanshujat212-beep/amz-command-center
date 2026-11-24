"""Proposal-time adapter for the same native-control predicate used at dispatch."""

from __future__ import annotations

import datetime as dt

from services.actions import state_machine as sm
from services.actions.native_controls import (
    NativeControlDecision,
    _state,
    evaluate_native_control,
    is_native_guarded_action,
)


def _campaign_id(action: sm.Action, metrics: dict) -> str | None:
    if action.action_type == "create_keyword":
        # The harvested term's source campaign is NOT necessarily its destination.
        destination = action.after_value.get("destination")
        value = destination.get("campaign_id") if isinstance(destination, dict) else None
    elif action.entity_type == "campaign":
        value = action.entity_id
    else:
        # Current keyword proposals use a settled, unique candidate-mart lineage.
        value = metrics.get("campaign_id")
    return str(value).strip() if value else None


def evaluate_proposed_native_control(
    cur,
    *,
    tenant_id: str,
    action_type: str,
    entity_type: str,
    entity_id: str,
    before_value: dict | None,
    after_value: dict,
    metrics_snapshot: dict,
    now: dt.datetime,
) -> NativeControlDecision:
    action = sm.Action("", tenant_id, entity_type, entity_id, action_type, before_value, after_value)
    state = None
    if is_native_guarded_action(action) and (campaign_id := _campaign_id(action, metrics_snapshot)):
        cur.execute(
            """
            select campaign_id, bidding_strategy, bidding_strategy_supported,
                   budget_rule_active, schedule_rule_active, rule_based_bidding_active,
                   cost_control_active, source_observed_at, source_api_version
              from campaign_native_control_state
             where tenant_id = %s and campaign_id = %s
             order by source_observed_at desc, loaded_at desc limit 1
            """,
            (tenant_id, campaign_id),
        )
        state = _state(cur.fetchone())
    return evaluate_native_control(action, state, now=now)
