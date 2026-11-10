"""Deterministic, bounded bid calculation over the R05.1 signal contract."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from services.rules.optimizer_signals import BidSignalSnapshot


@dataclass(frozen=True)
class EffectiveBidGoal:
    """Resolved goal values; sources can identify inherited goal scopes."""

    target_acos: float | None = None
    min_acos: float | None = None
    max_acos: float | None = None
    target_roas: float | None = None
    acos_ceiling: float | None = None
    profit_floor: float | None = None
    sources: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BidCalculationPolicy:
    min_bid: float
    max_bid: float
    max_change_pct: float
    min_clicks: int = 20
    min_impressions: int = 100
    max_data_age_days: int = 3


@dataclass(frozen=True)
class BidCalculationResult:
    status: str
    tenant_id: str
    entity_type: str
    entity_id: str
    before_bid: float | None
    proposed_bid: float | None
    delta_pct: float | None
    components: Mapping[str, float | None]
    reason_codes: tuple[str, ...]
    explanation: tuple[str, ...]
    goal_sources: Mapping[str, str]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["reason_codes"] = list(self.reason_codes)
        result["explanation"] = list(self.explanation)
        return result


def _finite(value: Any, *, positive: bool = False, nonnegative: bool = False) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    if positive and number <= 0:
        return None
    if nonnegative and number < 0:
        return None
    return number


def _component(signals: BidSignalSnapshot, name: str) -> float | None:
    item = signals.signals.get(name)
    if item is None or item.status != "observed":
        return None
    return _finite(item.value)


def _bounded_pressure(log_ratio: float) -> float:
    """Map a ratio to a smooth deterministic [-1, 1] pressure."""
    return math.tanh(log_ratio)


def _result(
    signals: BidSignalSnapshot,
    *,
    status: str,
    bid: float | None,
    proposed: float | None,
    delta_pct: float | None,
    reason: str,
    explanation: str,
    components: Mapping[str, float | None] | None = None,
    goal_sources: Mapping[str, str] | None = None,
) -> BidCalculationResult:
    return BidCalculationResult(
        status=status,
        tenant_id=signals.tenant_id,
        entity_type=signals.entity_type,
        entity_id=signals.entity_id,
        before_bid=bid,
        proposed_bid=proposed,
        delta_pct=delta_pct,
        components=dict(components or {}),
        reason_codes=(reason,),
        explanation=(explanation,),
        goal_sources=dict(goal_sources or {}),
    )


def calculate_bid(
    signals: BidSignalSnapshot,
    goal: EffectiveBidGoal,
    policy: BidCalculationPolicy,
) -> BidCalculationResult:
    """Return a bounded recommendation, hold, or fail-closed result.

    Goal performance and economics both affect the direction. Sample volume
    limits movement at low evidence levels, while CPC volatility reduces it.
    This function is pure and does not persist or apply the recommendation.
    """
    sources = goal.sources
    if signals.entity_type not in {"keyword", "target"}:
        return _result(
            signals,
            status="blocked",
            bid=None,
            proposed=None,
            delta_pct=None,
            reason="unsupported_entity",
            explanation="Bid optimization supports keyword and target entities only.",
            goal_sources=sources,
        )
    min_bid = _finite(policy.min_bid, nonnegative=True)
    max_bid = _finite(policy.max_bid, nonnegative=True)
    max_change = _finite(policy.max_change_pct, positive=True)
    if (
        min_bid is None
        or max_bid is None
        or max_bid < min_bid
        or max_change is None
        or max_change > 1
        or type(policy.min_clicks) is not int
        or policy.min_clicks < 1
        or type(policy.min_impressions) is not int
        or policy.min_impressions < 1
        or type(policy.max_data_age_days) is not int
        or policy.max_data_age_days < 0
    ):
        return _result(
            signals,
            status="blocked",
            bid=None,
            proposed=None,
            delta_pct=None,
            reason="invalid_policy",
            explanation="Bid bounds and evidence thresholds are invalid.",
            goal_sources=sources,
        )

    bid = _component(signals, "current_bid")
    if bid is None or bid <= 0:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="missing_current_bid",
            explanation="A positive settled current bid is required.",
            goal_sources=sources,
        )
    if bid < min_bid or bid > max_bid:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="current_bid_outside_bounds",
            explanation="Current bid is outside the active tenant bounds; resolve the policy drift first.",
            goal_sources=sources,
        )

    required = ("clicks", "impressions", "spend", "sales", "orders", "freshness_days")
    missing = [name for name in required if _component(signals, name) is None]
    match_type = signals.signals.get("match_type")
    if match_type is None or match_type.status != "observed" or not match_type.value:
        missing.append("match_type")
    if missing:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="required_signal_unavailable",
            explanation="Required settled signals are missing, partial, invalid, or undefined: "
            + ", ".join(missing),
            goal_sources=sources,
        )

    clicks = _component(signals, "clicks")
    impressions = _component(signals, "impressions")
    spend = _component(signals, "spend")
    sales = _component(signals, "sales")
    freshness = _component(signals, "freshness_days")
    if clicks is None or impressions is None or spend is None or sales is None or freshness is None:
        raise AssertionError("required signal validation lost a value")
    orders = _component(signals, "orders")
    if min(clicks, impressions, spend, sales, freshness, orders if orders is not None else -1) < 0:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="negative_performance_signal",
            explanation="Volume, spend, sales and freshness signals cannot be negative.",
            goal_sources=sources,
        )
    if freshness > policy.max_data_age_days:
        return _result(
            signals,
            status="hold",
            bid=bid,
            proposed=bid,
            delta_pct=0,
            reason="stale_data",
            explanation=f"Latest settled evidence is {freshness:g} days old.",
            goal_sources=sources,
        )
    if clicks < policy.min_clicks or impressions < policy.min_impressions:
        return _result(
            signals,
            status="hold",
            bid=bid,
            proposed=bid,
            delta_pct=0,
            reason="low_volume",
            explanation=f"Need at least {policy.min_clicks} clicks and {policy.min_impressions} impressions; observed {clicks:g} and {impressions:g}.",
            goal_sources=sources,
        )
    if sales <= 0:
        reason = (
            "zero_sales_with_orders"
            if _component(signals, "orders") not in (None, 0)
            else "zero_sales"
        )
        explanation = (
            "Sales are zero despite recorded orders; verify source data."
            if reason.endswith("orders")
            else "No settled attributed sales; hold the bid until performance evidence exists."
        )
        return _result(
            signals,
            status="hold" if reason == "zero_sales" else "blocked",
            bid=bid,
            proposed=bid if reason == "zero_sales" else None,
            delta_pct=0 if reason == "zero_sales" else None,
            reason=reason,
            explanation=explanation,
            goal_sources=sources,
        )
    if spend <= 0:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="sales_without_spend",
            explanation="Positive attributed sales with zero spend is inconsistent for this bid calculation.",
            goal_sources=sources,
        )

    acos = _component(signals, "acos")
    roas = _component(signals, "roas")
    break_even = _component(signals, "break_even_acos")
    if acos is None or acos <= 0 or roas is None or roas <= 0:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="performance_signal_unavailable",
            explanation="Positive settled ACoS and ROAS are required to evaluate the bid.",
            goal_sources=sources,
        )
    if break_even is None or break_even <= 0:
        return _result(
            signals,
            status="hold",
            bid=bid,
            proposed=bid,
            delta_pct=0,
            reason="economics_unavailable",
            explanation="A complete positive break-even ACoS is required before optimizing bids.",
            goal_sources=sources,
        )

    target_acos = _finite(goal.target_acos, positive=True)
    target_roas = _finite(goal.target_roas, positive=True)
    min_acos = _finite(goal.min_acos, nonnegative=True)
    max_acos = _finite(goal.max_acos, nonnegative=True)
    ceiling = _finite(goal.acos_ceiling, positive=True)
    profit_floor = _finite(goal.profit_floor)
    if (
        (goal.min_acos is not None and (min_acos is None or min_acos > 10))
        or (goal.max_acos is not None and (max_acos is None or max_acos > 10))
        or (goal.acos_ceiling is not None and (ceiling is None or ceiling > 10))
        or (target_acos is not None and target_acos > 10)
        or (profit_floor is not None and not -1 <= profit_floor <= 1)
    ):
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="invalid_goal",
            explanation="Resolved ACoS limits or profit floor are outside the supported range.",
            goal_sources=sources,
        )
    if goal.target_acos is not None and target_acos is None:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="invalid_goal",
            explanation="Target ACoS must be finite and positive.",
            goal_sources=sources,
        )
    if goal.target_roas is not None and target_roas is None:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="invalid_goal",
            explanation="Target ROAS must be finite and positive.",
            goal_sources=sources,
        )
    if goal.profit_floor is not None and profit_floor is None:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="invalid_goal",
            explanation="Profit floor must be a finite ratio.",
            goal_sources=sources,
        )
    if min_acos is not None and max_acos is not None and min_acos > max_acos:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="invalid_goal_range",
            explanation="Minimum ACoS exceeds maximum ACoS.",
            goal_sources=sources,
        )
    if target_acos is None and target_roas is None:
        return _result(
            signals,
            status="hold",
            bid=bid,
            proposed=bid,
            delta_pct=0,
            reason="target_missing",
            explanation="An effective target ACoS or target ROAS is required.",
            goal_sources=sources,
        )
    if target_acos is not None and min_acos is not None and target_acos < min_acos:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="target_below_min_acos",
            explanation="Target ACoS conflicts with the resolved minimum ACoS.",
            goal_sources=sources,
        )
    if target_acos is not None and max_acos is not None and target_acos > max_acos:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="target_above_max_acos",
            explanation="Target ACoS conflicts with the resolved maximum ACoS.",
            goal_sources=sources,
        )
    if target_acos is not None and target_roas is not None:
        reciprocal_error = abs(target_acos * target_roas - 1)
        if reciprocal_error > 0.05:
            return _result(
                signals,
                status="blocked",
                bid=bid,
                proposed=None,
                delta_pct=None,
                reason="conflicting_targets",
                explanation="Target ACoS and target ROAS are not reciprocal within 5%.",
                goal_sources=sources,
            )
    if ceiling is not None and target_acos is not None and target_acos > ceiling:
        return _result(
            signals,
            status="blocked",
            bid=bid,
            proposed=None,
            delta_pct=None,
            reason="target_above_acos_ceiling",
            explanation="Target ACoS exceeds the effective ACoS ceiling.",
            goal_sources=sources,
        )

    margin = _component(signals, "contribution_margin_pct")
    if profit_floor is not None and margin is None:
        return _result(
            signals,
            status="hold",
            bid=bid,
            proposed=bid,
            delta_pct=0,
            reason="profitability_signal_unavailable",
            explanation="The configured profit floor requires complete contribution-margin evidence.",
            goal_sources=sources,
        )

    acos_pressure = (
        _bounded_pressure(math.log(target_acos / acos)) if target_acos is not None else None
    )
    roas_pressure = (
        _bounded_pressure(math.log(roas / target_roas)) if target_roas is not None else None
    )
    goal_values = [value for value in (acos_pressure, roas_pressure) if value is not None]
    goal_pressure = sum(goal_values) / len(goal_values)
    economics_pressure = _bounded_pressure(math.log(break_even / acos))
    profit_pressure = (
        math.tanh((margin - profit_floor) * 2)
        if margin is not None and profit_floor is not None
        else None
    )
    if profit_pressure is None:
        score = 0.67 * goal_pressure + 0.33 * economics_pressure
    else:
        score = 0.55 * goal_pressure + 0.30 * economics_pressure + 0.15 * profit_pressure

    ceiling_pressure = None
    if ceiling is not None and acos > ceiling:
        ceiling_pressure = _bounded_pressure(math.log(ceiling / acos))
        score = min(score, ceiling_pressure)
    score = min(max(score, -1.0), 1.0)

    volume_weight = min(1.0, math.sqrt(clicks / (4 * policy.min_clicks)))
    volatility = _component(signals, "volatility_cpc_cv")
    stability_weight = 1.0 / (1.0 + max(0.0, volatility)) if volatility is not None else 0.75
    requested_delta = max(
        -max_change, min(max_change, score * max_change * volume_weight * stability_weight)
    )
    raw_bid = bid * (1.0 + requested_delta)
    bounded_bid = min(max(raw_bid, min_bid), max_bid)
    proposed = round(bounded_bid, 2)
    proposed = min(max(proposed, min_bid), max_bid)
    actual_delta = proposed / bid - 1.0
    components = {
        "goal_acos_pressure": acos_pressure,
        "goal_roas_pressure": roas_pressure,
        "goal_pressure": goal_pressure,
        "economics_pressure": economics_pressure,
        "profit_floor_pressure": profit_pressure,
        "acos_ceiling_pressure": ceiling_pressure,
        "combined_score": score,
        "volume_weight": volume_weight,
        "volatility_cpc_cv": volatility,
        "stability_weight": stability_weight,
        "requested_delta_pct": requested_delta,
    }
    reasons = ["optimizer_signal_blend"]
    explanations = [
        f"Combined goal pressure ({goal_pressure:.3f}) with break-even economics pressure ({economics_pressure:.3f}); target ACoS is not used alone.",
        f"Scaled the step by volume ({volume_weight:.3f}) and CPC stability ({stability_weight:.3f}).",
    ]
    if ceiling_pressure is not None:
        reasons.append("acos_ceiling_enforced")
        explanations.append("The effective ACoS ceiling forces a downward adjustment.")
    if raw_bid < min_bid:
        reasons.append("tenant_min_bid_clamp")
        explanations.append(f"The calculated bid was raised to tenant minimum {min_bid:.2f}.")
    elif raw_bid > max_bid:
        reasons.append("tenant_max_bid_clamp")
        explanations.append(f"The calculated bid was lowered to tenant maximum {max_bid:.2f}.")
    if proposed == bid:
        return BidCalculationResult(
            status="hold",
            tenant_id=signals.tenant_id,
            entity_type=signals.entity_type,
            entity_id=signals.entity_id,
            before_bid=bid,
            proposed_bid=bid,
            delta_pct=0.0,
            components=components,
            reason_codes=("rounded_no_change",),
            explanation=tuple(
                [*explanations, "The bounded recommendation rounds to the current bid."]
            ),
            goal_sources=dict(sources),
        )
    return BidCalculationResult(
        status="proposed",
        tenant_id=signals.tenant_id,
        entity_type=signals.entity_type,
        entity_id=signals.entity_id,
        before_bid=bid,
        proposed_bid=proposed,
        delta_pct=actual_delta,
        components=components,
        reason_codes=tuple(reasons),
        explanation=tuple(explanations),
        goal_sources=dict(sources),
    )
