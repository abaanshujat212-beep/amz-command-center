import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from services.rules.tos_optimizer import (
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
)
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
