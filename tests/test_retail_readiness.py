from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from services.rules.retail_readiness import (
    CommercialChange,
    CommercialHistory,
    RetailPolicy,
    RetailScope,
    RetailSnapshot,
    assess_retail_readiness,
)

NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
DAY = timedelta(days=1)
D = Decimal
SCOPE = RetailScope("tenant-a", "A1F83G8C2ARO7P", "sku-1", "GBP")
POLICY = RetailPolicy(2 * DAY, 2 * DAY, DAY, DAY, 5, D("2"), D(".35"), frozenset({"steady"}))
SNAPSHOT = RetailSnapshot(
    SCOPE, "verified_snapshot", NOW, 15, D("5"), True, True, D(".25"), "steady"
)
HISTORY = CommercialHistory(SCOPE, "authorized_export", NOW - 12 * DAY, NOW, ())


def assess(snapshot=SNAPSHOT, history=HISTORY, start=NOW - 7 * DAY):
    return assess_retail_readiness(
        SCOPE,
        POLICY,
        snapshot=snapshot,
        history=history,
        evidence_start=start,
        evidence_end=NOW,
        now=NOW,
    )


def test_stable_stock_tightens_economics_and_excess_does_not_relax_it():
    decision = assess(replace(SNAPSHOT, available_units=5000, days_of_supply=D("100")))
    assert decision.spend_increase_allowed
    assert decision.confidence == "known"
    assert decision.effective_acos_ceiling == D(".25")


@pytest.mark.parametrize(
    ("changes", "reason", "confidence"),
    [
        ({"available_units": 3}, "stock_below_floor", "known"),
        ({"days_of_supply": D("1.9")}, "days_of_supply_below_floor", "known"),
        ({"buy_box_won": False}, "buy_box_lost", "known"),
        ({"listing_sellable": False}, "listing_unavailable", "known"),
        ({"break_even_acos": D("0")}, "no_positive_margin", "known"),
        ({"lifecycle": "retired"}, "lifecycle_not_permitted", "known"),
        ({"buy_box_won": None}, "buy_box_unknown", "low"),
        ({"available_units": None}, "inventory_unknown", "low"),
        ({"break_even_acos": D("NaN")}, "economics_unknown", "low"),
        ({"observed_at": NOW - 3 * DAY}, "stale_or_unattributed_retail_snapshot", "low"),
        (
            {"scope": replace(SCOPE, tenant_id="other")},
            "missing_or_mismatched_retail_snapshot",
            "low",
        ),
    ],
)
def test_retail_blocks(changes, reason, confidence):
    result = assess(replace(SNAPSHOT, **changes))
    assert not result.spend_increase_allowed
    assert reason in result.reasons
    assert result.confidence == confidence


def test_changes_are_deterministic_during_dst_and_keep_latest_overlap():
    # British clocks go back at 01:00 UTC. Cooldowns are elapsed time.
    local = ZoneInfo("Europe/London")
    price = CommercialChange(
        SCOPE,
        "price",
        "authorized_export",
        "price",
        datetime(2026, 10, 25, 1, 30, tzinfo=local, fold=0),
        "12",
        "10",
    )
    coupon = CommercialChange(
        SCOPE,
        "coupon",
        "authorized_export",
        "coupon",
        datetime(2026, 10, 25, 1, 30, tzinfo=local, fold=1),
        "off",
        "promo-a",
    )
    decisions = [
        assess(history=replace(HISTORY, changes=events))
        for events in [(price, coupon), (coupon, price, coupon)]
    ]
    assert decisions[0] == decisions[1]
    assert not decisions[0].spend_increase_allowed
    assert [event.event_id for event in decisions[0].evidence] == ["price", "coupon"]
    assert decisions[0].unstable_until == datetime(2026, 10, 27, 0, 30, tzinfo=timezone.utc)


def test_expired_cooldown_requires_post_change_evidence():
    old = CommercialChange(SCOPE, "old", "authorized_export", "price", NOW - 5 * DAY, "12", "10")
    history = replace(HISTORY, changes=(old,))
    assert not assess(history=history).spend_increase_allowed
    assert assess(history=history, start=NOW - 2 * DAY).spend_increase_allowed


def test_partial_cross_scope_or_conflicting_history_fails_closed():
    a = CommercialChange(SCOPE, "same", "authorized_export", "price", NOW - 5 * DAY, "12", "10")
    histories = (
        None,
        replace(HISTORY, scope=replace(SCOPE, currency="USD")),
        replace(HISTORY, complete_from=NOW - 8 * DAY),
        replace(HISTORY, changes=(a, replace(a, after="11"))),
        replace(HISTORY, changes=(a, replace(a, event_id="new", effective_at=NOW - 4 * DAY))),
        replace(HISTORY, changes=(replace(a, after="non-price"),)),
    )
    for history in histories:
        result = assess(history=history)
        assert not result.spend_increase_allowed
        assert result.confidence == "low"


def test_ambiguous_same_id_during_dst_is_not_a_duplicate():
    local = ZoneInfo("Europe/London")
    price = CommercialChange(
        SCOPE,
        "price",
        "authorized_export",
        "price",
        datetime(2026, 10, 25, 1, 30, tzinfo=local, fold=0),
        "12",
        "10",
    )
    conflict = replace(price, effective_at=price.effective_at.replace(fold=1))
    result = assess(history=replace(HISTORY, changes=(price, conflict)))
    assert not result.spend_increase_allowed
    assert result.reasons == ("commercial_history_invalid",)
