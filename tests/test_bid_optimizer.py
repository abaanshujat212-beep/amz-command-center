import datetime as dt

import pytest

from services.rules.bid_optimizer import (
    BidCalculationPolicy,
    EffectiveBidGoal,
    calculate_bid,
)
from services.rules.optimizer_signals import build_bid_signal_snapshots

TODAY = dt.date(2026, 10, 10)


def snapshot(
    *, cost=15, sales=100, clicks=100, impressions=1000, orders=10, break_even=0.3, margin=0.2
):
    row = {
        "tenant_id": "tenant-a",
        "report_date": TODAY,
        "entity_type": "keyword",
        "entity_id": "keyword-1",
        "match_type": "exact",
        "bid": 1.25,
        "impressions": impressions,
        "clicks": clicks,
        "cost": cost,
        "attributed_sales_7d": sales,
        "attributed_orders_7d": orders,
        "break_even_acos": break_even,
        "contribution_margin_pct": margin,
        "is_settled": True,
    }
    return build_bid_signal_snapshots([row], tenant_id="tenant-a", through=TODAY, lookback_days=1)[
        0
    ]


def policy(**kwargs):
    values = dict(
        min_bid=0.1,
        max_bid=3.0,
        max_change_pct=0.2,
        min_clicks=20,
        min_impressions=100,
        max_data_age_days=3,
    )
    values.update(kwargs)
    return BidCalculationPolicy(**values)


def goal(**kwargs):
    values = {"target_acos": 0.2, "sources": {"target_acos": "keyword:kw-1"}}
    values.update(kwargs)
    return EffectiveBidGoal(**values)


def test_profitable_performance_generates_bounded_explainable_proposal():
    result = calculate_bid(snapshot(), goal(), policy())
    assert result.status == "proposed"
    assert result.proposed_bid > result.before_bid
    assert result.proposed_bid <= result.before_bid * 1.2
    assert result.components["goal_pressure"] > 0
    assert result.components["economics_pressure"] > 0
    assert "economics pressure" in result.explanation[0]
    assert result.goal_sources == {"target_acos": "keyword:kw-1"}


def test_high_acos_relative_to_goal_and_break_even_reduces_bid():
    result = calculate_bid(snapshot(cost=40, sales=100, break_even=0.3), goal(), policy())
    assert result.status == "proposed"
    assert result.proposed_bid < result.before_bid
    assert result.delta_pct >= -0.2


def test_zero_sales_and_low_volume_hold_without_bid_change():
    zero_sales = calculate_bid(snapshot(sales=0, orders=0), goal(), policy())
    low_volume = calculate_bid(snapshot(clicks=10, impressions=50), goal(), policy())
    assert (zero_sales.status, zero_sales.proposed_bid, zero_sales.reason_codes) == (
        "hold",
        1.25,
        ("zero_sales",),
    )
    assert (low_volume.status, low_volume.proposed_bid, low_volume.reason_codes) == (
        "hold",
        1.25,
        ("low_volume",),
    )


def test_economics_are_required_and_zero_sales_orders_conflict_is_blocked():
    no_economics = calculate_bid(snapshot(break_even=None), goal(), policy())
    conflict = calculate_bid(snapshot(sales=0, orders=2), goal(), policy())
    assert no_economics.reason_codes == ("economics_unavailable",)
    assert conflict.status == "blocked"
    assert conflict.reason_codes == ("zero_sales_with_orders",)


def test_tenant_bid_bounds_clamp_and_report_the_clamp():
    result = calculate_bid(snapshot(), goal(), policy(max_bid=1.26))
    assert result.proposed_bid == 1.26
    assert "tenant_max_bid_clamp" in result.reason_codes

    lower = calculate_bid(
        snapshot(cost=40, sales=100, break_even=0.3),
        goal(),
        policy(min_bid=1.24),
    )
    assert lower.proposed_bid == 1.24
    assert "tenant_min_bid_clamp" in lower.reason_codes


def test_target_acos_is_not_the_only_direction_signal():
    low_break_even = calculate_bid(snapshot(break_even=0.1), goal(), policy())
    high_break_even = calculate_bid(snapshot(break_even=0.3), goal(), policy())
    assert low_break_even.proposed_bid < high_break_even.proposed_bid
    assert low_break_even.components["goal_pressure"] == pytest.approx(
        high_break_even.components["goal_pressure"]
    )


def test_target_roas_only_is_a_supported_effective_goal():
    result = calculate_bid(snapshot(), goal(target_acos=None, target_roas=4), policy())
    assert result.status == "proposed"
    assert result.components["goal_acos_pressure"] is None
    assert result.components["goal_roas_pressure"] > 0


def test_missing_required_performance_data_blocks_calculation():
    incomplete = snapshot(cost=None)
    result = calculate_bid(incomplete, goal(), policy())
    assert result.status == "blocked"
    assert result.reason_codes == ("required_signal_unavailable",)


def test_stale_data_conflicting_targets_and_invalid_policy_fail_safely():
    stale_row = {
        "tenant_id": "tenant-a",
        "report_date": TODAY - dt.timedelta(days=4),
        "entity_type": "keyword",
        "entity_id": "keyword-1",
        "match_type": "exact",
        "bid": 1.25,
        "impressions": 1000,
        "clicks": 100,
        "cost": 15,
        "attributed_sales_7d": 100,
        "attributed_orders_7d": 10,
        "break_even_acos": 0.3,
        "is_settled": True,
    }
    stale = build_bid_signal_snapshots(
        [stale_row], tenant_id="tenant-a", through=TODAY, lookback_days=5
    )[0]
    stale_result = calculate_bid(stale, goal(), policy())
    conflict = calculate_bid(snapshot(), goal(target_roas=2), policy())
    invalid = calculate_bid(snapshot(), goal(), policy(max_change_pct=float("nan")))
    assert stale_result.reason_codes == ("stale_data",)
    assert conflict.reason_codes == ("conflicting_targets",)
    assert invalid.reason_codes == ("invalid_policy",)


def test_profit_floor_requires_margin_and_calculation_is_deterministic():
    missing_margin = calculate_bid(snapshot(margin=None), goal(profit_floor=0.1), policy())
    item = snapshot()
    first = calculate_bid(item, goal(), policy())
    second = calculate_bid(item, goal(), policy())
    assert missing_margin.reason_codes == ("profitability_signal_unavailable",)
    assert first.as_dict() == second.as_dict()
