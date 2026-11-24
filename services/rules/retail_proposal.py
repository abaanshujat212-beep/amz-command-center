"""Offline multi-product pre-proposal adapter. Never authorizes enqueue or apply."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from services.rules.retail_readiness import (
    CommercialHistory,
    RetailPolicy,
    RetailScope,
    RetailSnapshot,
    assess_retail_readiness,
)

_MAX_ADS = 5000
_NUMBER_ACTIONS = {
    "set_bid": {"keyword", "target", "ad_group"},
    "set_budget": {"campaign"},
    "set_placement_modifier": {"campaign"},
}
_INCREASE_ACTIONS = {
    "enable": {"campaign", "ad_group", "keyword", "target"},
    "create_keyword": {"search_term"},
    "create_target": {"ad_group"},
}
_NON_INCREASE_ACTIONS = {
    "pause",
    "flag",
    "add_negative_exact",
    "add_negative_phrase",
    "add_negative_product",
}


@dataclass(frozen=True)
class ImpactScope:
    tenant_id: str
    advertiser_profile_id: str
    marketplace_id: str
    currency: str
    campaign_id: str
    ad_group_id: str | None


@dataclass(frozen=True)
class GuardedProposal:
    scope: ImpactScope
    entity_type: str
    entity_id: str
    action_type: str
    before: Decimal | None
    after: Decimal | None
    existing_guards_allowed: bool


@dataclass(frozen=True)
class ImpactedAd:
    scope: ImpactScope
    ad_id: str
    ad_group_id: str
    sku: str
    asin: str


@dataclass(frozen=True)
class ImpactInventory:
    # These values come from the trusted resolver boundary, never inferred
    # from a performance report or accepted from a client.
    proposal: GuardedProposal
    observed_at: datetime
    complete: bool
    basis: Literal["current_prospective_eligibility", "historical_report"]
    ads: tuple[ImpactedAd, ...]


@dataclass(frozen=True)
class SkuEvidence:
    scope: ImpactScope
    sku: str
    asin: str
    retail_snapshot: RetailSnapshot | None
    commercial_history: CommercialHistory | None
    observation_basis: Literal["current_retail_observations", "historical_report"]
    # Attributed to this exact proposal blast radius and this SKU; a campaign
    # aggregate cannot supply these values even if all SKUs are otherwise safe.
    allocation_basis: Literal["settled_scope_sku_attribution", "aggregate"]
    performance_start: datetime
    performance_end: datetime
    attributed_spend: Decimal | None
    attributed_sales: Decimal | None


@dataclass(frozen=True)
class RetailProposalDecision:
    outcome: Literal["existing_guard_block", "not_applicable", "blocked", "retail_pass"]
    reasons: tuple[str, ...] = ()
    sku_failures: tuple[tuple[str, tuple[str, ...]], ...] = ()
    effective_acos_ceiling: Decimal | None = None
    # No production integration or enqueue path has been established.
    review_only: Literal[True] = field(init=False, default=True)


def _id(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 128 and value.strip() == value


def _number(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and 0 <= value <= 1_000_000_000_000


def _utc(value: object) -> datetime | None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _scope_valid(proposal: GuardedProposal) -> bool:
    scope = proposal.scope
    if not all(
        _id(x)
        for x in (
            scope.tenant_id,
            scope.advertiser_profile_id,
            scope.marketplace_id,
            scope.currency,
            scope.campaign_id,
            proposal.entity_id,
        )
    ):
        return False
    if proposal.entity_type == "campaign":
        return scope.ad_group_id is None and proposal.entity_id == scope.campaign_id
    if proposal.entity_type == "ad_group":
        return _id(scope.ad_group_id) and proposal.entity_id == scope.ad_group_id
    if proposal.entity_type in {"keyword", "target", "search_term"}:
        return _id(scope.ad_group_id)
    # A report-placement row is not the canonical campaign action identity.
    return False


def assess_retail_proposal(
    proposal: GuardedProposal,
    policy: RetailPolicy,
    *,
    inventory: ImpactInventory | None,
    evidence: tuple[SkuEvidence, ...],
    performance_start: datetime,
    performance_end: datetime,
    now: datetime,
) -> RetailProposalDecision:
    """Assess final guarded exposure against complete prospective SKU evidence.

    The boundary supplies the actual action destination and attestations.
    Nothing in this fixture adapter creates or proves provider evidence.
    """
    if proposal.existing_guards_allowed is not True:
        return RetailProposalDecision("existing_guard_block")
    if proposal.action_type in _NON_INCREASE_ACTIONS:
        return RetailProposalDecision("not_applicable")
    if proposal.action_type in _NUMBER_ACTIONS:
        if not _number(proposal.before) or not _number(proposal.after):
            return RetailProposalDecision("blocked", ("exposure_baseline_unknown",))
        if proposal.after <= proposal.before:
            return RetailProposalDecision("not_applicable")
    elif proposal.action_type not in _INCREASE_ACTIONS:
        return RetailProposalDecision("blocked", ("exposure_action_unknown",))

    supported_scopes = (_NUMBER_ACTIONS | _INCREASE_ACTIONS)[proposal.action_type]
    if proposal.entity_type not in supported_scopes or not _scope_valid(proposal):
        return RetailProposalDecision("blocked", ("retail_impact_scope_invalid",))
    clock, start, end = map(_utc, (now, performance_start, performance_end))
    if clock is None or start is None or end is None or not start < end <= clock:
        return RetailProposalDecision("blocked", ("retail_performance_window_invalid",))
    max_age = policy.max_snapshot_age
    if not isinstance(max_age, timedelta) or not timedelta(0) < max_age <= timedelta(days=365):
        return RetailProposalDecision("blocked", ("retail_policy_invalid",))
    observed = _utc(inventory.observed_at) if inventory is not None else None
    if (
        inventory is None
        or inventory.proposal != proposal
        or inventory.complete is not True
        or inventory.basis != "current_prospective_eligibility"
        or observed is None
        or not timedelta(0) <= clock - observed <= max_age
        or not 0 < len(inventory.ads) <= _MAX_ADS
    ):
        return RetailProposalDecision("blocked", ("retail_impact_inventory_unverified",))

    by_ad: dict[str, ImpactedAd] = {}
    by_sku: dict[str, str] = {}
    for ad in inventory.ads:
        if (
            ad.scope != proposal.scope
            or not all(_id(x) for x in (ad.ad_id, ad.ad_group_id, ad.sku, ad.asin))
            or (
                proposal.scope.ad_group_id is not None
                and ad.ad_group_id != proposal.scope.ad_group_id
            )
            or (ad.ad_id in by_ad and by_ad[ad.ad_id] != ad)
            or (ad.sku in by_sku and by_sku[ad.sku] != ad.asin)
        ):
            return RetailProposalDecision("blocked", ("retail_impact_inventory_conflict",))
        by_ad[ad.ad_id] = ad
        by_sku[ad.sku] = ad.asin

    if len(evidence) > len(by_sku):
        return RetailProposalDecision("blocked", ("retail_evidence_duplicate_or_outside_scope",))
    by_evidence: dict[str, SkuEvidence] = {}
    for row in evidence:
        if (
            row.scope != proposal.scope
            or row.sku not in by_sku
            or row.asin != by_sku[row.sku]
            or row.sku in by_evidence
        ):
            return RetailProposalDecision(
                "blocked", ("retail_evidence_duplicate_or_outside_scope",)
            )
        by_evidence[row.sku] = row

    failures = []
    observed_ratios = {}
    caps = []
    for sku in sorted(by_sku):
        row = by_evidence.get(sku)
        if row is None:
            failures.append((sku, ("sku_evidence_missing",)))
            continue
        if row.observation_basis != "current_retail_observations":
            failures.append((sku, ("current_retail_observation_missing",)))
            continue
        retail_scope = RetailScope(
            row.scope.tenant_id,
            row.scope.marketplace_id,
            sku,
            row.scope.currency,
        )
        decision = assess_retail_readiness(
            retail_scope,
            policy,
            snapshot=row.retail_snapshot,
            history=row.commercial_history,
            evidence_start=start,
            evidence_end=end,
            now=clock,
        )
        if not decision.spend_increase_allowed or decision.effective_acos_ceiling is None:
            failures.append((sku, decision.reasons or ("retail_readiness_not_proven",)))
            continue
        if (
            row.allocation_basis != "settled_scope_sku_attribution"
            or _utc(row.performance_start) != start
            or _utc(row.performance_end) != end
            or not _number(row.attributed_spend)
            or not _number(row.attributed_sales)
            or row.attributed_spend <= 0
            or row.attributed_sales <= 0
        ):
            failures.append((sku, ("sku_attributed_economics_unverified",)))
            continue
        caps.append(decision.effective_acos_ceiling)
        observed_ratios[sku] = (row.attributed_spend, row.attributed_sales)

    if failures or not caps:
        return RetailProposalDecision("blocked", ("retail_sku_readiness_blocked",), tuple(failures))
    # Use the most restrictive cap across the action scope and ACTUALLY
    # apply it to every SKU, so a strong SKU cannot average away a weaker one.
    cap = min(caps)
    excess = tuple(
        (sku, ("sku_acos_exceeds_effective_ceiling",))
        for sku, (spend, sales) in observed_ratios.items()
        if spend > sales * cap
    )
    if excess:
        return RetailProposalDecision("blocked", ("retail_economic_ceiling_blocked",), excess, cap)
    return RetailProposalDecision("retail_pass", effective_acos_ceiling=cap)
