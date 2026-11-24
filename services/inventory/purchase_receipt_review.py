"""Offline append-only purchase receipt review; never posts stock or cost."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID

_SCALE = 10_000
_QUANTITY = re.compile(r"[0-9]{1,8}(?:\.[0-9]{1,4})?")
_MAX_UNITS = 999_999_999_999


class ReceiptReviewError(ValueError):
    """Input, evidence or existing history cannot safely support the review."""


@dataclass(frozen=True)
class PurchaseOrder:
    tenant_id: UUID
    order_id: UUID
    supplier_sku: str
    quantity: str
    currency: str
    state: str


@dataclass(frozen=True)
class ReceivingLocation:
    tenant_id: UUID
    location_id: UUID
    marketplace_id: str | None
    active: bool


@dataclass(frozen=True)
class ReviewedSkuMapping:
    tenant_id: UUID
    order_id: UUID
    supplier_sku: str
    sellable_sku: str
    marketplace_id: str
    evidence_ref: str


@dataclass(frozen=True)
class ReceiptObservation:
    review_id: UUID
    actor_id: UUID
    location_id: UUID
    sellable_sku: str
    source_ref: str
    observed_at: datetime
    accepted: str
    damaged: str
    damage_evidence_ref: str | None = None


@dataclass(frozen=True)
class ReceiptEvent:
    tenant_id: UUID
    order_id: UUID
    review_id: UUID
    actor_id: UUID
    supplier_sku: str
    sellable_sku: str
    location_id: UUID
    marketplace_id: str
    mapping_evidence_ref: str
    currency: str
    source_ref: str
    observed_at: datetime
    accepted_units: int
    damaged_units: int
    damage_evidence_ref: str | None
    fingerprint: str


@dataclass(frozen=True)
class ReceiptReview:
    event: ReceiptEvent
    replay: bool
    accepted_units: int
    damaged_units: int
    outstanding_units: int


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 200:
        raise ReceiptReviewError(f"invalid {label}")
    if not value.isprintable():
        raise ReceiptReviewError(f"invalid {label}")
    return value


def _units(value: str) -> int:
    if not isinstance(value, str) or not _QUANTITY.fullmatch(value):
        raise ReceiptReviewError("quantity must have up to eight whole and four decimal digits")
    whole, _, fraction = value.partition(".")
    return int(whole) * _SCALE + int(fraction.ljust(4, "0"))


def _fingerprint(event: ReceiptEvent) -> str:
    # Version explicitly; changes in review serialization must not rewrite old evidence.
    payload = [
        "purchase_receipt_review_v1",
        str(event.tenant_id),
        str(event.order_id),
        str(event.review_id),
        str(event.actor_id),
        event.supplier_sku,
        event.sellable_sku,
        str(event.location_id),
        event.marketplace_id,
        event.mapping_evidence_ref,
        event.currency,
        event.source_ref,
        event.observed_at.isoformat(timespec="microseconds"),
        event.accepted_units,
        event.damaged_units,
        event.damage_evidence_ref,
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def review_receipt(
    *,
    tenant_id: UUID,
    order: PurchaseOrder,
    location: ReceivingLocation,
    mapping: ReviewedSkuMapping,
    observation: ReceiptObservation,
    prior_events: tuple[ReceiptEvent, ...],
) -> ReceiptReview:
    """Return a candidate event, or the previous identical event on replay.

    Caller supplies server-resolved records and a complete trusted per-order
    event history (explicitly empty only for a verified first receipt). A future persistence boundary must lock the PO, authorize
    the actor and atomically enforce scoped id/reference uniqueness.
    """
    if not all(
        isinstance(value, UUID)
        for value in (
            tenant_id,
            order.order_id,
            location.location_id,
            observation.review_id,
            observation.actor_id,
            observation.location_id,
        )
    ):
        raise ReceiptReviewError("invalid tenant, order, location, review or actor ID")
    if not (tenant_id == order.tenant_id == location.tenant_id == mapping.tenant_id):
        raise ReceiptReviewError("receipt scope is unavailable")
    supplier_sku = _text(order.supplier_sku, "purchase order SKU")
    sellable_sku = _text(mapping.sellable_sku, "mapped sellable SKU")
    market = _text(mapping.marketplace_id, "mapped marketplace")
    if (
        order.order_id != mapping.order_id
        or supplier_sku != mapping.supplier_sku
        or location.location_id != observation.location_id
        or sellable_sku != observation.sellable_sku
        or market != location.marketplace_id
    ):
        raise ReceiptReviewError("receipt scope is unavailable")
    if not isinstance(order.currency, str) or not re.fullmatch("[A-Z]{3}", order.currency):
        raise ReceiptReviewError("invalid purchase order currency")
    ordered = _units(order.quantity)
    accepted, damaged = _units(observation.accepted), _units(observation.damaged)
    if ordered == 0 or accepted + damaged == 0:
        raise ReceiptReviewError("positive order and receipt quantities are required")
    source = _text(observation.source_ref, "receipt source reference")
    proof = observation.damage_evidence_ref
    if damaged:
        _text(proof, "damage evidence reference")
    elif proof is not None:
        raise ReceiptReviewError("damage evidence requires a damaged quantity")
    timestamp = observation.observed_at
    if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
        raise ReceiptReviewError("receipt observation must be timezone-aware")
    candidate = ReceiptEvent(
        tenant_id=tenant_id,
        order_id=order.order_id,
        review_id=observation.review_id,
        actor_id=observation.actor_id,
        supplier_sku=supplier_sku,
        sellable_sku=sellable_sku,
        location_id=location.location_id,
        marketplace_id=market,
        mapping_evidence_ref=_text(mapping.evidence_ref, "SKU mapping evidence reference"),
        currency=order.currency,
        source_ref=source,
        observed_at=timestamp.astimezone(timezone.utc),
        accepted_units=accepted,
        damaged_units=damaged,
        damage_evidence_ref=proof,
        fingerprint="",
    )
    candidate = replace(candidate, fingerprint=_fingerprint(candidate))
    seen_ids: set[UUID] = set()
    seen_sources: set[str] = set()
    prior_accepted = prior_damaged = 0
    replay = None
    for event in prior_events:
        if (
            event.tenant_id != tenant_id
            or event.order_id != order.order_id
            or event.currency != order.currency
            or event.supplier_sku != supplier_sku
            or event.review_id in seen_ids
            or event.source_ref in seen_sources
            or not 0 <= event.accepted_units <= _MAX_UNITS
            or not 0 <= event.damaged_units <= _MAX_UNITS
            or event.accepted_units + event.damaged_units <= 0
            or event.fingerprint != _fingerprint(event)
        ):
            raise ReceiptReviewError("previous receipt evidence is inconsistent")
        seen_ids.add(event.review_id)
        seen_sources.add(event.source_ref)
        prior_accepted += event.accepted_units
        prior_damaged += event.damaged_units
        if event.review_id == candidate.review_id or event.source_ref == candidate.source_ref:
            if event != candidate:
                raise ReceiptReviewError("receipt identifier or source reference already used")
            replay = event
    if prior_accepted + prior_damaged > ordered:
        raise ReceiptReviewError("previous receipts exceed the physical purchase quantity")
    if replay is not None:
        return ReceiptReview(
            replay, True, prior_accepted, prior_damaged, ordered - prior_accepted - prior_damaged
        )
    if order.state != "issued" or location.active is not True:
        raise ReceiptReviewError("new receipts require an issued order and active location")
    accepted += prior_accepted
    damaged += prior_damaged
    if accepted + damaged > ordered:
        raise ReceiptReviewError("receipt exceeds the remaining physical purchase quantity")
    return ReceiptReview(candidate, False, accepted, damaged, ordered - accepted - damaged)
