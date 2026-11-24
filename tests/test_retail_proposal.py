from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from services.rules.retail_proposal import (
    GuardedProposal,
    ImpactedAd,
    ImpactInventory,
    ImpactScope,
    SkuEvidence,
    assess_retail_proposal,
)
from services.rules.retail_readiness import (
    CommercialHistory,
    RetailPolicy,
    RetailScope,
    RetailSnapshot,
)

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
DAY = timedelta(days=1)
START, END = NOW - 7 * DAY, NOW - DAY
SCOPE = ImpactScope("tenant", "crm-uk", "A1F83G8C2ARO7P", "GBP", "campaign-a", "group-a")
POLICY = RetailPolicy(DAY, DAY, DAY, DAY, 3, D("2"), D(".40"), frozenset({"steady"}))
PROPOSAL = GuardedProposal(SCOPE, "keyword", "kw", "set_bid", D(".5"), D(".6"), True)
ADS = (
    ImpactedAd(SCOPE, "ad-a", "group-a", "sku-a", "ASIN-A"),
    ImpactedAd(SCOPE, "ad-b", "group-a", "sku-b", "ASIN-B"),
)
INVENTORY = ImpactInventory(PROPOSAL, NOW, True, "current_prospective_eligibility", ADS)


def sku(ad):
    scope = RetailScope(SCOPE.tenant_id, SCOPE.marketplace_id, ad.sku, SCOPE.currency)
    return SkuEvidence(
        SCOPE,
        ad.sku,
        ad.asin,
        RetailSnapshot(scope, "authorized", NOW, 10, D("4"), True, True, D(".33"), "steady"),
        CommercialHistory(scope, "authorized", START - 2 * DAY, NOW, ()),
        "current_retail_observations",
        "settled_scope_sku_attribution",
        START,
        END,
        D("8"),
        D("40"),
    )


A, B = map(sku, ADS)


def assess(proposal=PROPOSAL, inventory=INVENTORY, evidence=(A, B)):
    return assess_retail_proposal(
        proposal,
        POLICY,
        inventory=inventory,
        evidence=evidence,
        performance_start=START,
        performance_end=END,
        now=NOW,
    )


def test_requires_every_eligible_sku_even_if_second_ad_had_no_history_rows():
    missing = assess(evidence=(A,))
    assert missing.outcome == "blocked"
    assert missing.sku_failures == (("sku-b", ("sku_evidence_missing",)),)
    sold_out = replace(B, retail_snapshot=replace(B.retail_snapshot, available_units=0))
    result = assess(evidence=(A, sold_out))
    assert result.outcome == "blocked"
    assert "stock_below_floor" in result.sku_failures[0][1]


@pytest.mark.parametrize(
    "inventory",
    [
        None,
        replace(INVENTORY, complete=False),
        replace(INVENTORY, basis="historical_report"),
        replace(INVENTORY, observed_at=NOW - 2 * DAY),
        replace(INVENTORY, ads=()),
        replace(INVENTORY, proposal=replace(PROPOSAL, after=D(".8"))),
        replace(
            INVENTORY,
            proposal=replace(PROPOSAL, scope=replace(SCOPE, advertiser_profile_id="other")),
        ),
    ],
)
def test_inventory_is_exact_current_prospective_and_complete(inventory):
    result = assess(inventory=inventory)
    assert result.outcome == "blocked"
    assert result.reasons == ("retail_impact_inventory_unverified",)


@pytest.mark.parametrize(
    "row",
    [
        replace(B, observation_basis="historical_report"),
        replace(B, retail_snapshot=replace(B.retail_snapshot, buy_box_won=None)),
        replace(B, retail_snapshot=replace(B.retail_snapshot, observed_at=NOW - 2 * DAY)),
        replace(
            B,
            retail_snapshot=replace(
                B.retail_snapshot, scope=replace(B.retail_snapshot.scope, marketplace_id="DE")
            ),
        ),
        replace(B, allocation_basis="aggregate"),
        replace(B, attributed_sales=D("0")),
        replace(B, attributed_spend=D("0")),
        replace(B, performance_end=END - DAY),
        replace(B, scope=replace(SCOPE, advertiser_profile_id="wrong")),
    ],
)
def test_missing_current_or_allocated_evidence_cannot_pass(row):
    assert assess(evidence=(A, row)).outcome == "blocked"


def test_applies_strictest_cap_to_each_sku_not_campaign_average():
    cautious = replace(B, retail_snapshot=replace(B.retail_snapshot, break_even_acos=D(".24")))
    passing = assess(evidence=(A, cautious))
    assert passing.review_only is True
    assert passing.outcome == "retail_pass"
    assert passing.effective_acos_ceiling == D(".24")
    above = assess(evidence=(replace(A, attributed_spend=D("11")), cautious))
    assert above.outcome == "blocked"
    assert above.sku_failures == (("sku-a", ("sku_acos_exceeds_effective_ceiling",)),)


def test_duplicates_and_destination_mismatches_are_not_used_to_prove_completeness():
    extra = replace(ADS[0], ad_id="another-id")
    assert assess(inventory=replace(INVENTORY, ads=(extra, *ADS))).outcome == "retail_pass"
    for ad in (
        replace(ADS[0], ad_group_id="out-of-scope"),
        replace(ADS[0], scope=replace(SCOPE, tenant_id="other")),
        replace(ADS[0], sku="a-conflicting-sku"),
        replace(ADS[0], ad_id="another-id", asin="other"),
    ):
        assert assess(inventory=replace(INVENTORY, ads=(*ADS, ad))).outcome == "blocked"


def test_campaign_action_must_prove_other_groups_too():
    campaign = replace(SCOPE, ad_group_id=None)
    action = GuardedProposal(
        campaign, "campaign", SCOPE.campaign_id, "set_budget", D("10"), D("12"), True
    )
    inventory = ImpactInventory(
        action,
        NOW,
        True,
        "current_prospective_eligibility",
        (replace(ADS[0], scope=campaign), replace(ADS[1], scope=campaign, ad_group_id="group-b")),
    )
    missing = assess(action, inventory, (replace(A, scope=campaign),))
    assert missing.outcome == "blocked"
    assert missing.sku_failures == (("sku-b", ("sku_evidence_missing",)),)


def test_unknown_baseline_or_unsupported_action_does_not_look_like_a_reduction():
    assert assess(replace(PROPOSAL, before=None), None, ()).reasons == (
        "exposure_baseline_unknown",
    )
    assert assess(replace(PROPOSAL, action_type="unknown"), None, ()).reasons == (
        "exposure_action_unknown",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"after": D(".4")},
        {"after": D(".5")},
        {"action_type": "pause"},
        {"action_type": "flag"},
        {"action_type": "add_negative_exact"},
    ],
)
def test_existing_safe_nonincreases_bypass_missing_retail(change):
    assert assess(replace(PROPOSAL, **change), None, ()).outcome == "not_applicable"


def test_retail_cannot_override_native_or_guardrail_block():
    assert (
        assess(replace(PROPOSAL, existing_guards_allowed=False)).outcome == "existing_guard_block"
    )


def test_enable_requires_prospective_inventory_instead_of_pre_activation_only():
    enable = replace(PROPOSAL, action_type="enable", before=None, after=None)
    assert assess(enable, INVENTORY).outcome == "blocked"
    assert assess(enable, replace(INVENTORY, proposal=enable), (A,)).outcome == "blocked"
