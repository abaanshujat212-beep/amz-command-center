"""Deterministic FIFO, weighted-average and by-period batch COGS allocation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Literal

Method = Literal["fifo", "weighted_average", "by_period"]


@dataclass(frozen=True)
class Receipt:
    id: str
    received_at: str
    quantity: Decimal
    unit_cost: Decimal
    currency: str = "GBP"


@dataclass(frozen=True)
class Sale:
    ref: str
    sold_at: str
    quantity: Decimal
    currency: str = "GBP"


@dataclass(frozen=True)
class Allocation:
    sale_ref: str
    batch_id: str | None
    quantity: Decimal
    unit_cost: Decimal | None
    allocated_cost: Decimal | None
    sequence: int


@dataclass(frozen=True)
class Calculation:
    allocations: tuple[Allocation, ...]
    complete: bool
    incomplete_reason: str | None
    input_hash: str


def _hash(method: Method, receipts: list[Receipt], sales: list[Sale]) -> str:
    payload = {"method": method, "receipts": [asdict(x) for x in receipts], "sales": [asdict(x) for x in sales]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def calculate(method: Method, receipts: list[Receipt], sales: list[Sale]) -> Calculation:
    if method not in {"fifo", "weighted_average", "by_period"}:
        raise ValueError(f"unsupported COGS method: {method}")
    ordered_receipts = sorted(receipts, key=lambda x: (x.received_at, x.id))
    ordered_sales = sorted(sales, key=lambda x: (x.sold_at, x.ref))
    currencies = {x.currency for x in [*ordered_receipts, *ordered_sales]}
    if len(currencies) > 1:
        raise ValueError("all inputs must use one currency; FX belongs in an adjustment")
    if any(x.quantity <= 0 or x.unit_cost < 0 for x in ordered_receipts):
        raise ValueError("receipt quantity must be positive and cost non-negative")
    if any(x.quantity == 0 for x in ordered_sales):
        raise ValueError("sale quantity cannot be zero")
    if method == "fifo":
        allocations, reason = _fifo(ordered_receipts, ordered_sales)
    else:
        allocations, reason = _average(ordered_receipts, ordered_sales, by_period=method == "by_period")
    return Calculation(tuple(allocations), reason is None, reason, _hash(method, ordered_receipts, ordered_sales))


def _fifo(receipts: list[Receipt], sales: list[Sale]) -> tuple[list[Allocation], str | None]:
    remaining = {item.id: item.quantity for item in receipts}
    output: list[Allocation] = []
    reason = None
    for sale in sales:
        if sale.quantity < 0:
            previous = next((x for x in reversed(output) if x.unit_cost is not None), None)
            cost = previous.unit_cost if previous else None
            output.append(Allocation(sale.ref, previous.batch_id if previous else None, sale.quantity, cost, sale.quantity * cost if cost is not None else None, 0))
            if cost is None:
                reason = "return_without_prior_cost"
            continue
        needed = sale.quantity
        sequence = 0
        for batch in receipts:
            if batch.received_at > sale.sold_at or needed <= 0:
                continue
            used = min(remaining[batch.id], needed)
            if used > 0:
                output.append(Allocation(sale.ref, batch.id, used, batch.unit_cost, used * batch.unit_cost, sequence))
                remaining[batch.id] -= used
                needed -= used
                sequence += 1
        if needed > 0:
            output.append(Allocation(sale.ref, None, needed, None, None, sequence))
            reason = "negative_stock"
    return output, reason


def _average(receipts: list[Receipt], sales: list[Sale], *, by_period: bool) -> tuple[list[Allocation], str | None]:
    output: list[Allocation] = []
    reason = None
    for sale in sales:
        eligible = [x for x in receipts if x.received_at <= sale.sold_at]
        if by_period:
            eligible = [x for x in eligible if x.received_at[:7] == sale.sold_at[:7]]
        quantity = sum((x.quantity for x in eligible), Decimal(0))
        if quantity <= 0:
            output.append(Allocation(sale.ref, None, sale.quantity, None, None, 0))
            reason = "negative_stock" if sale.quantity > 0 else "return_without_prior_cost"
            continue
        average = sum((x.quantity * x.unit_cost for x in eligible), Decimal(0)) / quantity
        output.append(Allocation(sale.ref, eligible[-1].id, sale.quantity, average, sale.quantity * average, 0))
    return output, reason
