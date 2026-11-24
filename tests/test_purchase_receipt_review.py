from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from services.inventory.purchase_receipt_review import (
    PurchaseOrder,
    ReceiptObservation,
    ReceiptReviewError,
    ReceivingLocation,
    ReviewedSkuMapping,
    review_receipt,
)


def uid(n):
    return UUID(int=n)


TENANT = uid(1)
ORDER = PurchaseOrder(TENANT, uid(2), "supplier-01", "10.0001", "GBP", "issued")
LOCATION = ReceivingLocation(TENANT, uid(3), "UK", True)
MAPPING = ReviewedSkuMapping(
    TENANT, ORDER.order_id, "supplier-01", "sellable-01", "UK", "mapping-1"
)
OBSERVATION = ReceiptObservation(
    uid(4),
    uid(5),
    LOCATION.location_id,
    "sellable-01",
    "dock-ticket:1",
    datetime(2026, 11, 23, 12, tzinfo=timezone.utc),
    "5.5",
    "1",
    "damage-ticket:1",
)


def review(**kwargs):
    param = dict(
        prior_events=(),
        tenant_id=TENANT,
        order=ORDER,
        location=LOCATION,
        mapping=MAPPING,
        observation=OBSERVATION,
    )
    return review_receipt(**(param | kwargs))


def test_split_receipts_and_retries_do_not_double_count_dispositions():
    first = review()
    assert (first.accepted_units, first.damaged_units, first.outstanding_units) == (
        55_000,
        10_000,
        35_001,
    )
    location = replace(LOCATION, location_id=uid(7))
    second_input = replace(
        OBSERVATION,
        review_id=uid(8),
        location_id=location.location_id,
        source_ref="dock-ticket:2",
        accepted="3.5001",
        damaged="0",
        damage_evidence_ref=None,
    )
    second = review(observation=second_input, location=location, prior_events=(first.event,))
    assert (second.accepted_units, second.damaged_units, second.outstanding_units) == (
        90_001,
        10_000,
        0,
    )

    zone = timezone(timedelta(hours=5))
    reordered = (second.event, first.event)
    again = review(
        observation=replace(
            OBSERVATION, accepted="5.5000", observed_at=OBSERVATION.observed_at.astimezone(zone)
        ),
        prior_events=reordered,
    )
    assert again.replay and again.event is first.event
    assert (again.accepted_units, again.damaged_units, again.outstanding_units) == (
        90_001,
        10_000,
        0,
    )
    with pytest.raises(ReceiptReviewError, match="remaining physical"):
        review(
            observation=replace(second_input, review_id=uid(9), source_ref="dock-ticket:3"),
            location=location,
            prior_events=reordered,
        )


@pytest.mark.parametrize(
    "update",
    [
        {"accepted": "5.5001"},
        {"actor_id": uid(10)},
        {"review_id": uid(12)},
        {"source_ref": "different"},
        {"damage_evidence_ref": "different-damage-proof"},
        {"observed_at": OBSERVATION.observed_at + timedelta(seconds=1)},
    ],
)
def test_conflicting_identifier_or_reference_never_replays(update):
    with pytest.raises(ReceiptReviewError, match="already used"):
        review(observation=replace(OBSERVATION, **update), prior_events=(review().event,))


@pytest.mark.parametrize(
    "override",
    [
        {"location": replace(LOCATION, tenant_id=uid(11))},
        {"location": replace(LOCATION, marketplace_id=None)},
        {"location": replace(LOCATION, marketplace_id="US")},
        {"mapping": replace(MAPPING, tenant_id=uid(12))},
        {"mapping": replace(MAPPING, order_id=uid(12))},
        {"mapping": replace(MAPPING, supplier_sku="another-supplier")},
        {"observation": replace(OBSERVATION, location_id=uid(12))},
        {"observation": replace(OBSERVATION, sellable_sku=ORDER.supplier_sku)},
    ],
)
def test_missing_or_unrelated_scope_is_blocked(override):
    with pytest.raises(ReceiptReviewError, match="scope is unavailable"):
        review(**override)


@pytest.mark.parametrize(
    "update",
    [
        {"accepted": "-1"},
        {"accepted": "1e1"},
        {"accepted": "0.00001"},
        {"accepted": 2.0},
        {"accepted": "100000000"},
        {"damage_evidence_ref": None},
        {"damage_evidence_ref": "   "},
        {"damaged": "0"},
        {"observed_at": OBSERVATION.observed_at.replace(tzinfo=None)},
    ],
)
def test_invalid_observations_are_blocked(update):
    with pytest.raises(ReceiptReviewError):
        review(observation=replace(OBSERVATION, **update))


def test_new_receipts_need_issued_order_and_active_location_but_exact_retry_remains_stable():
    expected = review()
    for override in (
        {"order": replace(ORDER, state="draft")},
        {"location": replace(LOCATION, active=False)},
    ):
        with pytest.raises(ReceiptReviewError, match="issued order and active location"):
            review(**override)
    result = review(
        order=replace(ORDER, state="cancelled"),
        location=replace(LOCATION, active=False),
        prior_events=(expected.event,),
    )
    assert result.replay and result.event is expected.event


def test_replay_still_rejects_mixed_tenant_or_duplicate_history():
    event = review().event
    for events in (
        (event, replace(event, tenant_id=uid(10))),
        (event, event),
        (replace(event, damaged_units=0),),
    ):
        with pytest.raises(ReceiptReviewError, match="previous receipt evidence"):
            review(prior_events=events)


def test_one_physical_receipt_can_be_all_damaged_and_does_not_claim_sellable_stock():
    reviewed = review(observation=replace(OBSERVATION, accepted="0", damaged=ORDER.quantity))
    assert reviewed.accepted_units == reviewed.event.accepted_units == 0
    assert reviewed.outstanding_units == 0
    assert reviewed.event.damaged_units == 100_001


def test_missing_history_is_not_assumed_to_be_empty():
    with pytest.raises(TypeError, match="prior_events"):
        review_receipt(
            tenant_id=TENANT,
            order=ORDER,
            location=LOCATION,
            mapping=MAPPING,
            observation=OBSERVATION,
        )
