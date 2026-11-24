"""Proposal-only Sponsored Products Top-of-Search optimizer (R09.3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class TopOfSearchPolicy:
    tenant_id: str
    profile_id: str
    currency: str
    selected_keyword_ids: frozenset[str]
    target_impression_share: Decimal
    max_base_bid: Decimal
    max_bid_step: Decimal
    max_modifier_pct: int
    max_modifier_step_pct: int
    max_acos: Decimal
    max_incremental_daily_spend: Decimal
    min_clicks: int
    min_orders: int
    max_age: timedelta
    max_effective_top_bid: Decimal | None = None


@dataclass(frozen=True)
class AudienceBoostSnapshot:
    tenant_id: str
    profile_id: str
    campaign_id: str
    marketplace: str
    currency: str
    bidding_strategy: str
    observed_at: datetime
    source_revision: str
    complete: bool
    # A verified empty inventory is (), not None. IDs are never serialized.
    adjustments: tuple[tuple[str, int], ...] | None


@dataclass(frozen=True)
class TopOfSearchEvidence:
    tenant_id: str
    profile_id: str
    campaign_id: str
    keyword_id: str
    currency: str
    window_start: datetime
    window_end: datetime
    loaded_at: datetime
    impression_share: Decimal
    current_base_bid: Decimal
    current_modifier_pct: int
    other_max_modifier_pct: int
    keyword_spend: Decimal
    keyword_sales: Decimal
    top_spend: Decimal
    top_sales: Decimal
    top_clicks: int
    top_impressions: int
    top_orders: int
    peak_daily_keyword_clicks: int
    break_even_acos: Decimal
    campaign_daily_budget: Decimal
    peak_daily_campaign_spend: Decimal
    # Complete, fresh, trusted inventory of ALL enabled targeting in the
    # campaign, across ad groups. None means unknown, not empty.
    campaign_only_target_is_this_keyword: bool | None = None
    campaign_target_inventory_at: datetime | None = None
    audience_snapshot: AudienceBoostSnapshot | None = None


@dataclass(frozen=True)
class Candidate:
    action_type: Literal["set_bid", "set_placement_modifier"]
    entity_type: Literal["keyword", "campaign"]
    entity_id: str
    before_value: Decimal
    after_value: Decimal
    placement: str | None
    reason: str = "strategic_keyword_below_top_of_search_share_goal"
    requires_explicit_approval: bool = True


@dataclass(frozen=True)
class TopOfSearchPlan:
    candidates: tuple[Candidate, ...]
    blocked: tuple[str, ...]
    evidence: TopOfSearchEvidence | None = None
    effective_acos_ceiling: Decimal | None = None
    combined_top_bid: Decimal | None = None
    estimated_incremental_daily_spend: Decimal | None = None
    audience_expires_at: datetime | None = None


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        raise ValueError("invalid numeric evidence")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or result > Decimal("1000000000"):
        raise ValueError("invalid numeric evidence")
    return result


def _counts(*values: object) -> bool:
    return all(type(value) is int and 0 <= value <= 1_000_000_000 for value in values)


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def maximum_audience_boost(
    evidence: TopOfSearchEvidence, snapshot: AudienceBoostSnapshot | None,
    *, now: datetime, max_age: timedelta,
) -> int | None:
    if (
        snapshot is None or snapshot.complete is not True
        or (snapshot.tenant_id, snapshot.profile_id, snapshot.campaign_id, snapshot.currency)
        != (evidence.tenant_id, evidence.profile_id, evidence.campaign_id, evidence.currency)
        or snapshot.marketplace != "GB" or snapshot.currency != "GBP"
        or snapshot.bidding_strategy != "fixed"
        or not isinstance(snapshot.source_revision, str) or not snapshot.source_revision.strip()
        or not _aware(snapshot.observed_at)
        or not now - max_age <= snapshot.observed_at <= now
        or not isinstance(snapshot.adjustments, tuple)
    ):
        return None
    seen = set()
    winning = 0
    for row in snapshot.adjustments:
        if not isinstance(row, tuple) or len(row) != 2:
            return None
        audience_id, boost = row
        if (
            not isinstance(audience_id, str) or not audience_id.strip() or audience_id in seen
            or type(boost) is not int or not 0 <= boost <= 900
        ):
            return None
        seen.add(audience_id)
        winning = max(winning, boost)
    return winning


def plan_top_of_search(
    policy: TopOfSearchPolicy,
    evidence: TopOfSearchEvidence,
    *,
    now: datetime,
    bid_native_allowed: bool,
    placement_native_allowed: bool,
) -> TopOfSearchPlan:
    """Evaluate validated repository inputs; never enqueue or call Amazon.

    A percentage point modifier is applied to the base bid, not a keyword
    setting. The cost stress scenario holds click volume at the observed
    keyword peak and assumes the entire bid increase is realized as CPC.
    This is not an Amazon spend, impression-share, or price guarantee.
    """
    if (
        evidence.tenant_id != policy.tenant_id
        or evidence.profile_id != policy.profile_id
        or evidence.currency != policy.currency
    ):
        return TopOfSearchPlan((), ("evidence_scope_mismatch",))
    if not evidence.keyword_id or evidence.keyword_id not in policy.selected_keyword_ids:
        return TopOfSearchPlan((), ("keyword_not_selected",))
    if not all(
        isinstance(x, str) and x.strip()
        for x in (evidence.tenant_id, evidence.profile_id, evidence.campaign_id, evidence.currency)
    ):
        return TopOfSearchPlan((), ("unscoped_evidence",))
    if (
        not isinstance(policy.max_age, timedelta)
        or policy.max_age <= timedelta(0)
        or not all(
            _aware(x) for x in (now, evidence.window_start, evidence.window_end, evidence.loaded_at)
        )
        or not evidence.window_start < evidence.window_end <= evidence.loaded_at <= now
        or now - evidence.window_end > policy.max_age
        or now - evidence.loaded_at > policy.max_age
    ):
        return TopOfSearchPlan((), ("stale_or_invalid_performance_window",))
    try:
        share, target_share, acos, break_even = map(
            _decimal,
            (
                evidence.impression_share,
                policy.target_impression_share,
                policy.max_acos,
                evidence.break_even_acos,
            ),
        )
        bid, max_bid, bid_step, max_spend, budget, spent = map(
            _decimal,
            (
                evidence.current_base_bid,
                policy.max_base_bid,
                policy.max_bid_step,
                policy.max_incremental_daily_spend,
                evidence.campaign_daily_budget,
                evidence.peak_daily_campaign_spend,
            ),
        )
        spend, sales, top_spend, top_sales = map(
            _decimal,
            (
                evidence.keyword_spend,
                evidence.keyword_sales,
                evidence.top_spend,
                evidence.top_sales,
            ),
        )
        if not (
            0 < target_share <= 1
            and share <= 1
            and 0 < acos <= 1
            and 0 < break_even <= 1
            and 0 < bid <= max_bid
            and bid % _CENT == 0
            and bid_step >= _CENT
            and max_spend > 0
            and budget > 0
            and _counts(
                policy.min_clicks,
                policy.min_orders,
                policy.max_modifier_pct,
                policy.max_modifier_step_pct,
                evidence.current_modifier_pct,
                evidence.other_max_modifier_pct,
                evidence.top_clicks,
                evidence.top_impressions,
                evidence.top_orders,
                evidence.peak_daily_keyword_clicks,
            )
            and 0 <= evidence.current_modifier_pct <= policy.max_modifier_pct <= 900
            and evidence.other_max_modifier_pct <= 900
            and 1 <= policy.max_modifier_step_pct <= 900
            and policy.min_clicks > 0
            and policy.min_orders > 0
        ):
            raise ValueError("values outside policy bounds")
    except (ValueError, InvalidOperation):
        return TopOfSearchPlan((), ("invalid_evidence_or_policy",))
    if share >= target_share:
        return TopOfSearchPlan((), ("share_goal_met",), evidence)
    if (
        evidence.top_clicks < policy.min_clicks
        or evidence.top_orders < policy.min_orders
        or evidence.peak_daily_keyword_clicks <= 0
        or min(spend, sales, top_spend, top_sales) <= 0
        or top_spend > spend
        or top_sales > sales
        or evidence.top_orders > evidence.top_clicks
        or evidence.top_clicks > evidence.top_impressions
    ):
        return TopOfSearchPlan((), ("low_or_inconsistent_placement_data",), evidence)

    audience_pct = maximum_audience_boost(
        evidence, evidence.audience_snapshot, now=now, max_age=policy.max_age,
    )
    if audience_pct is None:
        return TopOfSearchPlan((), ("audience_or_fixed_bid_evidence_unavailable",), evidence)
    try:
        effective_cap = _decimal(policy.max_effective_top_bid)
        if effective_cap <= 0:
            raise ValueError("effective ceiling must be positive")
    except (ValueError, InvalidOperation):
        return TopOfSearchPlan((), ("effective_top_bid_ceiling_unavailable",), evidence)
    audience_factor = 1 + Decimal(audience_pct) / 100

    ceiling = min(acos, break_even)
    if spend / sales >= ceiling or top_spend / top_sales >= ceiling:
        return TopOfSearchPlan((), ("acos_or_economics_ceiling",), evidence, ceiling)
    headroom = min(max_spend, budget - spent)
    if headroom <= 0:
        return TopOfSearchPlan((), ("no_campaign_budget_headroom",), evidence, ceiling)

    def effective(base: Decimal, pct: int) -> Decimal:
        return base * (1 + Decimal(pct) / 100) * audience_factor

    before_pct = evidence.current_modifier_pct
    current = effective(bid, before_pct)
    other_factor = (1 + Decimal(evidence.other_max_modifier_pct) / 100) * audience_factor
    max_base_budget = bid + headroom / evidence.peak_daily_keyword_clicks / other_factor
    max_cpc = min(
        effective_cap,
        ceiling * top_sales / evidence.top_clicks,
        current + headroom / evidence.peak_daily_keyword_clicks,
    )
    if current >= effective_cap:
        return TopOfSearchPlan((), ("effective_top_bid_ceiling_reached",), evidence, ceiling, current)
    if max_cpc <= current:
        return TopOfSearchPlan((), ("no_effective_bid_headroom",), evidence, ceiling)

    gap = (target_share - share) / target_share
    # Split available headroom. If only one leg is eligible it can use
    # all headroom. Final scenario is checked for any combination.
    inventory_at = evidence.campaign_target_inventory_at
    isolated = (
        evidence.campaign_only_target_is_this_keyword is True
        and _aware(inventory_at)
        and now - policy.max_age <= inventory_at <= now
    )
    bid_allowed = bid_native_allowed is True
    modifier_allowed = placement_native_allowed is True and isolated
    blocked = []
    if not bid_allowed:
        blocked.append("native_control_blocks_bid")
    if placement_native_allowed is not True:
        blocked.append("native_control_blocks_placement")
    if not isolated:
        blocked.append("campaign_placement_would_affect_unselected_or_unknown_targets")

    candidates = []
    base_after = bid
    after_pct = before_pct
    if bid_allowed:
        bid_ceiling = current + (max_cpc - current) / (2 if modifier_allowed else 1)
        raw = min(
            max_bid,
            max_base_budget,
            bid + max(_CENT, bid_step * gap),
            bid_ceiling / ((1 + Decimal(before_pct) / 100) * audience_factor),
        )
        base_after = raw // _CENT * _CENT
        if base_after > bid:
            candidates.append(
                Candidate("set_bid", "keyword", evidence.keyword_id, bid, base_after, None)
            )
    if modifier_allowed:
        pct_within_joint_cap = int((max_cpc / (base_after * audience_factor) - 1) * 100)
        after_pct = min(
            policy.max_modifier_pct,
            before_pct + max(1, int(policy.max_modifier_step_pct * gap)),
            pct_within_joint_cap,
        )
        # Rounding in Decimal division must never add a point above the cap.
        if effective(base_after, after_pct) > max_cpc:
            after_pct -= 1
        after_pct = max(before_pct, after_pct)
        if after_pct > before_pct:
            candidates.append(
                Candidate(
                    "set_placement_modifier",
                    "campaign",
                    evidence.campaign_id,
                    Decimal(before_pct),
                    Decimal(after_pct),
                    "PLACEMENT_TOP",
                )
            )
    combined = effective(base_after, after_pct)
    stress_cost = max(combined - current, (base_after - bid) * other_factor)
    stress_cost *= evidence.peak_daily_keyword_clicks
    if not candidates or combined > max_cpc or stress_cost > headroom:
        return TopOfSearchPlan((), (*blocked, "no_bounded_increase"), evidence, ceiling)
    return TopOfSearchPlan(
        tuple(candidates),
        tuple(blocked),
        evidence,
        ceiling,
        combined,
        stress_cost,
        evidence.audience_snapshot.observed_at + policy.max_age,
    )
