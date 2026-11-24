"""Offline retail risk policy. Does not ingest data, approve, or enqueue actions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

ChangeKind = Literal["price", "coupon", "lifecycle"]
Lifecycle = Literal["launch", "steady", "clearance", "retired"]


@dataclass(frozen=True)
class RetailScope:
    tenant_id: str
    marketplace_id: str
    sku: str
    currency: str


@dataclass(frozen=True)
class RetailSnapshot:
    scope: RetailScope
    source: str
    observed_at: datetime
    available_units: int | None
    days_of_supply: Decimal | None
    buy_box_won: bool | None
    listing_sellable: bool | None
    break_even_acos: Decimal | None
    lifecycle: Lifecycle | None


@dataclass(frozen=True)
class CommercialChange:
    scope: RetailScope
    event_id: str
    source: str
    kind: ChangeKind
    effective_at: datetime
    before: str
    after: str


@dataclass(frozen=True)
class CommercialHistory:
    scope: RetailScope
    source: str
    # Trusted observation of complete history across all three change
    # families, not merely the earliest and latest event seen.
    complete_from: datetime
    complete_through: datetime
    changes: tuple[CommercialChange, ...]


@dataclass(frozen=True)
class RetailPolicy:
    max_snapshot_age: timedelta
    price_stabilization: timedelta
    coupon_stabilization: timedelta
    lifecycle_stabilization: timedelta
    min_available_units: int
    min_days_of_supply: Decimal
    max_acos: Decimal
    permitted_lifecycle: frozenset[Lifecycle]


@dataclass(frozen=True)
class RetailDecision:
    spend_increase_allowed: bool
    confidence: Literal["known", "low"]
    reasons: tuple[str, ...]
    effective_acos_ceiling: Decimal | None
    unstable_until: datetime | None
    evidence: tuple[CommercialChange, ...] = ()


_LIFECYCLES = frozenset({"launch", "steady", "clearance", "retired"})


def _utc(value: object) -> datetime | None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _decimal(value: object, *, unit_interval: bool = False) -> bool:
    return (
        isinstance(value, Decimal)
        and value.is_finite()
        and 0 <= value
        and (not unit_interval or value <= 1)
    )


def _transition_is_valid(change: CommercialChange) -> bool:
    if not (
        isinstance(change.before, str)
        and isinstance(change.after, str)
        and 0 < len(change.before) <= 120
        and 0 < len(change.after) <= 120
        and change.before.strip() == change.before
        and change.after.strip() == change.after
        and change.before != change.after
    ):
        return False
    if change.kind == "lifecycle":
        return {change.before, change.after} <= _LIFECYCLES
    if change.kind == "price":
        try:
            before, after = Decimal(change.before), Decimal(change.after)
        except InvalidOperation:
            return False
        return _decimal(before) and _decimal(after) and min(before, after) > 0 and before != after
    return True


def assess_retail_readiness(
    scope: RetailScope,
    policy: RetailPolicy,
    *,
    snapshot: RetailSnapshot | None,
    history: CommercialHistory | None,
    evidence_start: datetime,
    evidence_end: datetime,
    now: datetime,
) -> RetailDecision:
    """Reject spend increases on incomplete data; never relax the base ACoS cap.

    Effective timestamps are compared in UTC: durations are elapsed time,
    not counts of local calendar hours. Historical performance must start
    after the most recent relevant change's stabilization period.
    """
    clock, start, end = map(_utc, (now, evidence_start, evidence_end))
    durations = {
        "price": policy.price_stabilization,
        "coupon": policy.coupon_stabilization,
        "lifecycle": policy.lifecycle_stabilization,
    }
    if not (
        all((scope.tenant_id, scope.marketplace_id, scope.sku, scope.currency))
        and clock is not None
        and start is not None
        and end is not None
        and start < end <= clock
        and all(
            isinstance(d, timedelta) and timedelta(0) < d <= timedelta(days=365)
            for d in [policy.max_snapshot_age, *durations.values()]
        )
        and type(policy.min_available_units) is int
        and policy.min_available_units >= 1
        and _decimal(policy.min_days_of_supply)
        and policy.min_days_of_supply > 0
        and _decimal(policy.max_acos, unit_interval=True)
        and policy.max_acos > 0
        and policy.permitted_lifecycle <= _LIFECYCLES - {"retired"}
    ):
        return RetailDecision(False, "low", ("invalid_policy_or_window",), None, None)

    reasons = []
    incomplete = False
    cap = None
    if snapshot is None or snapshot.scope != scope:
        reasons.append("missing_or_mismatched_retail_snapshot")
        incomplete = True
    else:
        seen = _utc(snapshot.observed_at)
        if (
            not snapshot.source
            or seen is None
            or not clock - policy.max_snapshot_age <= seen <= clock
        ):
            reasons.append("stale_or_unattributed_retail_snapshot")
            incomplete = True
        else:
            if type(snapshot.available_units) is not int or snapshot.available_units < 0:
                reasons.append("inventory_unknown")
                incomplete = True
            elif snapshot.available_units < policy.min_available_units:
                reasons.append("stock_below_floor")
            if not _decimal(snapshot.days_of_supply):
                reasons.append("days_of_supply_unknown")
                incomplete = True
            elif snapshot.days_of_supply < policy.min_days_of_supply:
                reasons.append("days_of_supply_below_floor")
            if snapshot.buy_box_won is False:
                reasons.append("buy_box_lost")
            elif snapshot.buy_box_won is not True:
                incomplete = True
                reasons.append("buy_box_unknown")
            if snapshot.listing_sellable is False:
                reasons.append("listing_unavailable")
            elif snapshot.listing_sellable is not True:
                incomplete = True
                reasons.append("listing_unknown")
            if not _decimal(snapshot.break_even_acos, unit_interval=True):
                reasons.append("economics_unknown")
                incomplete = True
            elif snapshot.break_even_acos == 0:
                reasons.append("no_positive_margin")
            else:
                cap = min(snapshot.break_even_acos, policy.max_acos)
            if snapshot.lifecycle not in _LIFECYCLES:
                incomplete = True
                reasons.append("lifecycle_unknown")
            elif snapshot.lifecycle not in policy.permitted_lifecycle:
                reasons.append("lifecycle_not_permitted")

    unstable_until = None
    changes: list[CommercialChange] = []
    coverage_start = _utc(history.complete_from) if history is not None else None
    coverage_end = _utc(history.complete_through) if history is not None else None
    if (
        history is None
        or history.scope != scope
        or not history.source.strip()
        or coverage_start is None
        or coverage_end is None
        or not coverage_start
        <= start - max(durations.values())
        < start
        < end
        <= coverage_end
        <= clock
        or clock - coverage_end > policy.max_snapshot_age
    ):
        reasons.append("commercial_history_incomplete")
        incomplete = True
    else:
        by_id: dict[str, CommercialChange] = {}
        for change in history.changes:
            t = _utc(change.effective_at)
            if t is not None:
                change = replace(change, effective_at=t)
            if (
                change.scope != scope
                or not change.event_id
                or not change.source
                or change.kind not in durations
                or t is None
                or not coverage_start <= t <= coverage_end
                or not _transition_is_valid(change)
                or (change.event_id in by_id and by_id[change.event_id] != change)
            ):
                reasons.append("commercial_history_invalid")
                incomplete = True
                by_id.clear()
                break
            by_id[change.event_id] = change
        latest_by_kind: dict[str, CommercialChange] = {}
        seen = (
            _utc(snapshot.observed_at) if snapshot is not None and snapshot.scope == scope else None
        )
        for change in sorted(
            by_id.values(), key=lambda event: (_utc(event.effective_at), event.event_id)
        ):
            prior = latest_by_kind.get(change.kind)
            if prior is not None and (
                _utc(prior.effective_at) == _utc(change.effective_at)
                or prior.after != change.before
            ):
                reasons.append("commercial_history_ambiguous")
                incomplete = True
                changes.clear()
                unstable_until = None
                break
            latest_by_kind[change.kind] = change
            cutoff = _utc(change.effective_at) + durations[change.kind]
            if cutoff > start:
                changes.append(change)
                unstable_until = max(cutoff, unstable_until or cutoff)
        lifecycle_change = latest_by_kind.get("lifecycle")
        if (
            lifecycle_change is not None
            and snapshot is not None
            and snapshot.scope == scope
            and _utc(snapshot.observed_at) is not None
            and _utc(snapshot.observed_at) >= _utc(lifecycle_change.effective_at)
            and snapshot.lifecycle != lifecycle_change.after
        ):
            reasons.append("lifecycle_snapshot_mismatch")
            incomplete = True
        if seen is not None and any(
            _utc(event.effective_at) > seen for event in latest_by_kind.values()
        ):
            reasons.append("snapshot_predates_commercial_change")
            incomplete = True
        if unstable_until is not None:
            reasons.append("performance_spans_unstable_or_superseded_regime")
    return RetailDecision(
        not reasons,
        "low" if incomplete else "known",
        tuple(reasons),
        cap,
        unstable_until,
        tuple(changes),
    )
