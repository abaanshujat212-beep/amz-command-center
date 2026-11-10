import datetime as dt

import pytest

from services.rules.optimizer_signals import (
    OPTIONAL_SIGNALS,
    REQUIRED_SIGNALS,
    SignalContractError,
    build_bid_signal_snapshots,
)

THROUGH = dt.date(2026, 10, 10)


def test_contract_declares_required_and_optional_signal_sets():
    assert {"current_bid", "cpc", "acos", "roas", "match_type", "freshness_days"} <= set(REQUIRED_SIGNALS)
    assert {"break_even_acos", "placement", "volatility_cpc_cv", "organic_rank", "inventory_days"} <= set(OPTIONAL_SIGNALS)


def row(day, **overrides):
    item = {
        "tenant_id": "tenant-a",
        "report_date": THROUGH - dt.timedelta(days=day),
        "entity_type": "keyword",
        "entity_id": "keyword-1",
        "match_type": "exact",
        "bid": 1.25,
        "impressions": 100,
        "clicks": 10,
        "cost": 10.0,
        "attributed_sales_7d": 50.0,
        "attributed_orders_7d": 2,
        "break_even_acos": 0.3,
        "contribution_margin_pct": 0.2,
        "is_settled": True,
    }
    item.update(overrides)
    return item


def test_snapshots_are_tenant_scoped_settled_and_aggregated_before_ratios():
    rows = [
        row(0, cost=30, clicks=10, attributed_sales_7d=100, attributed_orders_7d=4),
        row(1, cost=10, clicks=10, attributed_sales_7d=50, attributed_orders_7d=2),
        row(2, cost=500, is_settled=False),
        row(1, tenant_id="tenant-b", cost=999),
        row(4, cost=400),  # outside inclusive three-day window
    ]
    snapshot, = build_bid_signal_snapshots(
        rows, tenant_id="tenant-a", through=THROUGH, lookback_days=3
    )

    assert (snapshot.tenant_id, snapshot.entity_type, snapshot.entity_id) == (
        "tenant-a", "keyword", "keyword-1"
    )
    assert (snapshot.observed_days, snapshot.settled_days) == (3, 2)
    assert snapshot.signals["spend"].value == 40
    assert snapshot.signals["sales"].value == 150
    assert snapshot.signals["cpc"].value == 2
    assert snapshot.signals["acos"].value == pytest.approx(40 / 150)
    assert snapshot.signals["roas"].value == pytest.approx(150 / 40)
    assert snapshot.signals["cpc"].source_relation == "marts.mart_ppc_keyword_daily"
    assert snapshot.signals["cpc"].source_ref == "keyword:keyword-1:2026-10-08:2026-10-10"


def test_zero_denominators_are_undefined_and_observed_zero_is_preserved():
    snapshot, = build_bid_signal_snapshots(
        [row(0, impressions=0, clicks=0, cost=0, attributed_sales_7d=0)],
        tenant_id="tenant-a", through=THROUGH, lookback_days=1,
    )
    assert snapshot.signals["clicks"].value == 0
    assert snapshot.signals["clicks"].status == "observed"
    for key in ("cpc", "acos", "roas"):
        assert snapshot.signals[key].value is None
        assert snapshot.signals[key].status == "undefined"


def test_missing_optional_inputs_are_explicit_and_rank_requires_provenance():
    snapshot, = build_bid_signal_snapshots(
            [row(0, contribution_margin_pct=None)], tenant_id="tenant-a", through=THROUGH, lookback_days=1,
        context_signals={
            ("keyword", "keyword-1"): {
                "organic_rank": {"value": 12, "source": "provider-x", "source_ref": "snapshot-7", "observed_at": THROUGH},
                "share_of_voice": {"value": 1.2, "source": "provider-x", "source_ref": "snapshot-7", "observed_at": THROUGH},
                "buy_box_share": {"value": 0.5},
                "contribution_margin_pct": {"value": -0.1, "source": "cost-ledger", "source_ref": "sku-1", "observed_at": THROUGH},
            }
        },
    )
    assert snapshot.signals["organic_rank"].value == 12
    assert snapshot.signals["organic_rank"].source_relation == "provider-x"
    assert snapshot.signals["share_of_voice"].value is None
    assert snapshot.signals["share_of_voice"].status == "invalid"
    assert "documented range" in snapshot.signals["share_of_voice"].reason
    assert snapshot.signals["buy_box_share"].status == "invalid"
    assert snapshot.signals["contribution_margin_pct"].value == pytest.approx(-0.1)
    assert snapshot.signals["placement"].status == "missing"


def test_volatility_requires_two_daily_cpc_values_and_marks_partial_coverage():
    partial, = build_bid_signal_snapshots(
        [row(0, clicks=10, cost=10), row(1, clicks=None, cost=5)],
        tenant_id="tenant-a", through=THROUGH, lookback_days=2,
    )
    assert partial.signals["volatility_cpc_cv"].status == "insufficient_data"

    full, = build_bid_signal_snapshots(
        [row(0, clicks=10, cost=10), row(1, clicks=10, cost=20)],
        tenant_id="tenant-a", through=THROUGH, lookback_days=2,
    )
    assert full.signals["volatility_cpc_cv"].status == "observed"
    assert full.signals["volatility_cpc_cv"].value > 0


def test_duplicate_entity_day_and_unsupported_entity_fail_closed():
    with pytest.raises(SignalContractError, match="duplicate settled row"):
        build_bid_signal_snapshots(
            [row(0), row(0)], tenant_id="tenant-a", through=THROUGH, lookback_days=1
        )
    with pytest.raises(SignalContractError, match="unsupported bid entity"):
        build_bid_signal_snapshots(
            [row(0, entity_type="search_term")],
            tenant_id="tenant-a", through=THROUGH, lookback_days=1,
        )


def test_match_type_conflict_is_invalid_not_guessed():
    snapshot, = build_bid_signal_snapshots(
        [row(0), row(1, match_type="broad")],
        tenant_id="tenant-a", through=THROUGH, lookback_days=2,
    )
    assert snapshot.signals["match_type"].value is None
    assert snapshot.signals["match_type"].status == "invalid"
