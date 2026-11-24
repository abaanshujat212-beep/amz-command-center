import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from services.rules.tos_optimizer import (
    AudienceBoostSnapshot,
    TopOfSearchEvidence,
    TopOfSearchPolicy,
    plan_top_of_search,
)
from services.rules.tos_recommendations import review_top_of_search

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
DAY = timedelta(days=1)
POLICY = TopOfSearchPolicy(
    "tenant",
    "profile",
    "GBP",
    frozenset({"k"}),
    D(".40"),
    D("1"),
    D(".2"),
    120,
    50,
    D(".35"),
    D("4"),
    20,
    3,
    2 * DAY,
    D("2.00"),
)
AUDIENCE = AudienceBoostSnapshot("tenant", "profile", "c", "GB", "GBP", "fixed", NOW, "rev-1", True, ())
EVIDENCE = TopOfSearchEvidence(
    "tenant",
    "profile",
    "c",
    "k",
    "GBP",
    NOW - 8 * DAY,
    NOW - DAY,
    NOW,
    D(".10"),
    D(".50"),
    20,
    35,
    D("20"),
    D("120"),
    D("12"),
    D("100"),
    40,
    300,
    5,
    10,
    D(".30"),
    D("20"),
    D("15"),
    True,
    NOW - DAY,
    AUDIENCE,
)


def plan(policy=POLICY, evidence=EVIDENCE, *, bid=True, placement=True):
    return plan_top_of_search(
        policy,
        evidence,
        now=NOW,
        bid_native_allowed=bid,
        placement_native_allowed=placement,
    )


class TestTopOfSearch(unittest.TestCase):
    def test_separate_candidates_and_joint_caps(self):
        result = plan()
        bid, placement = result.candidates
        assert (bid.action_type, bid.entity_id, bid.after_value) == ("set_bid", "k", D(".56"))
        assert (placement.action_type, placement.entity_id, placement.placement) == (
            "set_placement_modifier",
            "c",
            "PLACEMENT_TOP",
        )
        assert all(x.requires_explicit_approval for x in result.candidates)
        assert result.effective_acos_ceiling == D(".30")
        assert result.combined_top_bid <= D(".75")
        assert result.estimated_incremental_daily_spend <= POLICY.max_incremental_daily_spend
        assert result == plan()

    def test_holds_or_blocks_without_guessing(self):
        for change, reason in [
            ({"tenant_id": "other"}, "evidence_scope_mismatch"),
            ({"profile_id": "other"}, "evidence_scope_mismatch"),
            ({"currency": "USD"}, "evidence_scope_mismatch"),
            ({"keyword_id": "untargeted"}, "keyword_not_selected"),
            ({"impression_share": D(".41")}, "share_goal_met"),
            ({"window_end": NOW - 3 * DAY}, "stale_or_invalid_performance_window"),
            ({"loaded_at": NOW + DAY}, "stale_or_invalid_performance_window"),
            ({"top_orders": 1}, "low_or_inconsistent_placement_data"),
            ({"top_sales": D("0")}, "low_or_inconsistent_placement_data"),
            ({"top_sales": D("210")}, "low_or_inconsistent_placement_data"),
            ({"top_spend": D("15"), "top_sales": D("42")}, "acos_or_economics_ceiling"),
            ({"keyword_spend": D("39")}, "acos_or_economics_ceiling"),
            ({"peak_daily_campaign_spend": D("20")}, "no_campaign_budget_headroom"),
            ({"impression_share": D("NaN")}, "invalid_evidence_or_policy"),
        ]:
            with self.subTest(change=change):
                result = plan(evidence=replace(EVIDENCE, **change))
                assert not result.candidates
                assert reason in result.blocked

    def test_native_conflicts_resolve_independently_and_unknown_blocks(self):
        for opts, expected in [
            ({"bid": True, "placement": False}, ["set_bid"]),
            ({"bid": False, "placement": True}, ["set_placement_modifier"]),
            ({"bid": None, "placement": None}, []),
        ]:
            with self.subTest(opts=opts):
                assert [x.action_type for x in plan(**opts).candidates] == expected

    def test_old_or_incomplete_inventory_never_gives_campaign_placement(self):
        for inventory in [None, False, True]:
            with self.subTest(inventory=inventory):
                result = plan(
                    evidence=replace(
                        EVIDENCE,
                        campaign_only_target_is_this_keyword=inventory,
                        campaign_target_inventory_at=NOW - 3 * DAY,
                    )
                )
                assert [x.action_type for x in result.candidates] == ["set_bid"]
                assert (
                    "campaign_placement_would_affect_unselected_or_unknown_targets"
                    in result.blocked
                )

    def test_budget_headroom_honors_combination_even_when_incremental_cap_is_larger(self):
        result = plan(evidence=replace(EVIDENCE, peak_daily_campaign_spend=D("19.75")))
        assert result.candidates
        assert result.estimated_incremental_daily_spend <= D(".25")

    def test_budget_accounts_for_other_placement_multipliers(self):
        result = plan(
            evidence=replace(
                EVIDENCE, peak_daily_campaign_spend=D("19.65"), other_max_modifier_pct=240
            ),
            placement=False,
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].after_value == D(".51")
        assert result.estimated_incremental_daily_spend == D(".3400")

    def test_canonical_review_contract_never_executes(self):
        rows = review_top_of_search(
            plan(),
            now=NOW,
            current_audience_snapshot=AUDIENCE,
            objective_snapshot={"code": "STRATEGIC_VISIBILITY"},
            strategy_snapshot={"code": "TOP_OF_SEARCH"},
        )
        assert json.loads(json.dumps(rows)) == rows
        bid, placement = rows
        assert bid["recommendation_type"] == "bid_adjustment"
        assert placement["recommendation_type"] == "placement_adjustment"
        assert placement["after_value"]["placement"] == "PLACEMENT_TOP"
        assert not placement["expected_behavior"]["approval_capability_registered"]
        for row in rows:
            behavior = row["expected_behavior"]
            assert behavior["requires_human_approval"]
            assert not behavior["executable"]
            assert not behavior["automation_enabled"]

    def test_unknown_audience_or_non_fixed_bidding_fails_closed(self):
        for snapshot in [
            None,
            replace(AUDIENCE, adjustments=None),
            replace(AUDIENCE, complete=False),
            replace(AUDIENCE, observed_at=NOW - 3 * DAY),
            replace(AUDIENCE, campaign_id="wrong"),
            replace(AUDIENCE, marketplace="US"),
            replace(AUDIENCE, bidding_strategy="dynamic_up_down"),
            replace(AUDIENCE, adjustments=(("dup", 20), ("dup", 60))),
        ]:
            result = plan(evidence=replace(EVIDENCE, audience_snapshot=snapshot))
            assert not result.candidates
            assert "audience_or_fixed_bid_evidence_unavailable" in result.blocked
        assert plan().candidates  # explicit complete empty inventory
        assert not plan(policy=replace(POLICY, max_effective_top_bid=None)).candidates

    def test_combo_stress_uses_highest_audience_and_never_rounds_into_cap(self):
        boosted = replace(AUDIENCE, adjustments=(("lower", 30), ("higher", 60)))
        baseline = replace(
            EVIDENCE, audience_snapshot=boosted, current_base_bid=D("1.00"),
            current_modifier_pct=50, top_sales=D("400"), keyword_sales=D("500"),
        )
        result = plan(evidence=baseline)
        assert not result.candidates
        assert result.combined_top_bid == D("2.40")
        assert "effective_top_bid_ceiling_reached" in result.blocked

        # A placement-only +50% from zero would be £2.40; the planner may reduce it.
        lower = plan(
            policy=replace(POLICY, max_modifier_step_pct=100),
            evidence=replace(baseline, current_modifier_pct=0),
            bid=False,
        )
        assert len(lower.candidates) == 1
        assert lower.candidates[0].after_value == D("25")
        assert lower.combined_top_bid == D("2.00")

        # £2.004 is not allowed through a £2.00 cap just because it rounds down.
        almost = plan(evidence=replace(
            baseline, current_modifier_pct=20,
            audience_snapshot=replace(AUDIENCE, adjustments=(("only", 67),)),
        ))
        assert almost.combined_top_bid == D("2.004")
        assert not almost.candidates

    def test_changed_audience_even_at_same_max_requires_new_review(self):
        original = replace(AUDIENCE, adjustments=(("original", 20),))
        result = plan(evidence=replace(EVIDENCE, audience_snapshot=original))
        assert result.candidates
        params = {"objective_snapshot":{}, "strategy_snapshot":{}}
        assert review_top_of_search(result, now=NOW, current_audience_snapshot=original, **params)
        changed = replace(original, adjustments=(("different", 20),))
        assert not review_top_of_search(result, now=NOW, current_audience_snapshot=changed, **params)
        assert not review_top_of_search(result, now=NOW+3*DAY, current_audience_snapshot=original, **params)

    def test_other_placement_stress_multiplies_audience_factor(self):
        boosted = replace(AUDIENCE, adjustments=(("only", 60),))
        result = plan(
            evidence=replace(
                EVIDENCE, audience_snapshot=boosted, peak_daily_campaign_spend=D("19.45"),
                other_max_modifier_pct=240, top_sales=D("200"), keyword_sales=D("250"),
            ),
            placement=False,
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].after_value == D(".51")
        assert result.estimated_incremental_daily_spend == D(".544")
