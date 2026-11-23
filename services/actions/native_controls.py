"""Fail-closed conflict checks for Amazon-native campaign optimization."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from services.actions import state_machine as sm

MAX_EVIDENCE_AGE = dt.timedelta(hours=24)
SUPPORTED_STRATEGIES = {"fixed", "dynamic_down_only", "dynamic_up_down"}


def is_native_guarded_action(action: sm.Action) -> bool:
    return (
        (action.action_type == "set_bid" and action.entity_type in {"keyword", "target", "ad_group"})
        or (action.action_type == "create_keyword" and action.entity_type == "search_term")
        or (action.action_type in {"set_placement_modifier", "set_budget", "pause", "enable"} and action.entity_type == "campaign")
    )


@dataclass(frozen=True)
class NativeControlState:
    campaign_id: str
    bidding_strategy: str
    bidding_strategy_supported: bool
    budget_rule_active: bool
    schedule_rule_active: bool
    rule_based_bidding_active: bool
    cost_control_active: bool
    source_observed_at: dt.datetime
    source_api_version: str


@dataclass(frozen=True)
class NativeControlDecision:
    allowed: bool
    reason_code: str | None
    explanation: str
    ownership_options: tuple[str, ...] = ()


def evaluate_native_control(
    action: sm.Action,
    state: NativeControlState | None,
    *,
    now: dt.datetime,
) -> NativeControlDecision:
    """Return whether an already-approved action remains safe to dispatch."""
    if not is_native_guarded_action(action):
        return NativeControlDecision(True, None, "Action does not overlap an Amazon-native campaign control.")
    if state is None:
        return NativeControlDecision(False, "NATIVE_CONTROL_EVIDENCE_MISSING", "No current Amazon native-control snapshot exists for this campaign.")
    observed = state.source_observed_at
    if observed.tzinfo is None:
        return NativeControlDecision(False, "NATIVE_CONTROL_EVIDENCE_INVALID", "Native-control source timestamp has no timezone.")
    if observed > now + dt.timedelta(minutes=5):
        return NativeControlDecision(False, "NATIVE_CONTROL_EVIDENCE_INVALID", "Native-control source timestamp is in the future.")
    if now - observed > MAX_EVIDENCE_AGE:
        return NativeControlDecision(False, "NATIVE_CONTROL_EVIDENCE_STALE", "Amazon native-control evidence is older than 24 hours.")
    if not state.bidding_strategy_supported or state.bidding_strategy not in SUPPORTED_STRATEGIES:
        return NativeControlDecision(False, "NATIVE_CONTROL_UNSUPPORTED", f"Amazon bidding strategy {state.bidding_strategy!r} is preserved but unsupported.")

    bid_action = (action.action_type == "set_bid" and action.entity_type in {"keyword", "target", "ad_group"}) or (action.action_type == "create_keyword" and action.entity_type == "search_term")
    placement_action = action.action_type == "set_placement_modifier" and action.entity_type == "campaign"
    budget_action = action.action_type == "set_budget" and action.entity_type == "campaign"
    campaign_state_action = action.action_type in {"pause", "enable"} and action.entity_type == "campaign"

    conflicts: list[str] = []
    if bid_action and (state.bidding_strategy != "fixed" or state.rule_based_bidding_active or state.cost_control_active):
        conflicts.append("Amazon-native bid optimization")
    if placement_action and (state.rule_based_bidding_active or state.cost_control_active):
        conflicts.append("Amazon rule-based bidding or cost control")
    if budget_action and state.budget_rule_active:
        conflicts.append("Amazon budget rule")
    if campaign_state_action and state.schedule_rule_active:
        conflicts.append("Amazon schedule rule")
    if conflicts:
        return NativeControlDecision(
            False,
            "NATIVE_OPTIMIZATION_CONFLICT",
            f"Action conflicts with {', '.join(conflicts)}.",
            ("keep_amazon_control", "propose_separate_control_transfer"),
        )
    return NativeControlDecision(True, None, "No conflicting Amazon-native control is active.")


def _state(row: dict[str, Any] | None) -> NativeControlState | None:
    if not row or not row.get("campaign_id"):
        return None
    return NativeControlState(
        campaign_id=str(row["campaign_id"]),
        bidding_strategy=str(row["bidding_strategy"]),
        bidding_strategy_supported=bool(row["bidding_strategy_supported"]),
        budget_rule_active=bool(row["budget_rule_active"]),
        schedule_rule_active=bool(row["schedule_rule_active"]),
        rule_based_bidding_active=bool(row["rule_based_bidding_active"]),
        cost_control_active=bool(row["cost_control_active"]),
        source_observed_at=row["source_observed_at"],
        source_api_version=str(row["source_api_version"]),
    )


def load_native_control_state(cur, action: sm.Action) -> NativeControlState | None:
    """Resolve campaign lineage and load its latest append-only snapshot."""
    cur.execute(
        """
        select s.campaign_id, s.bidding_strategy, s.bidding_strategy_supported,
               s.budget_rule_active, s.schedule_rule_active,
               s.rule_based_bidding_active, s.cost_control_active,
               s.source_observed_at, s.source_api_version
          from action a
          left join rule_evaluation e
            on e.tenant_id = a.tenant_id and e.id = a.evaluation_id
          left join lateral (
            select n.* from campaign_native_control_state n
             where n.tenant_id = a.tenant_id
               and n.campaign_id = coalesce(
                 nullif(a.after_value->>'campaign_id',''),
                 nullif(a.before_value->>'campaign_id',''),
                 nullif(e.metrics_snapshot->>'campaign_id',''),
                 case when a.entity_type = 'campaign' then a.entity_id end
               )
             order by n.source_observed_at desc, n.loaded_at desc limit 1
          ) s on true
         where a.tenant_id = %s and a.id = %s
        """,
        (action.tenant_id, action.id),
    )
    return _state(cur.fetchone())
