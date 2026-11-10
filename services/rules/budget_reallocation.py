"""Pure, approval-gated portfolio budget reallocation proposals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Iterable

CENT = Decimal("0.01")


@dataclass(frozen=True)
class BudgetCandidate:
    campaign_id: str
    daily_budget: Decimal
    minimum_budget: Decimal
    maximum_budget: Decimal
    efficiency: Decimal


@dataclass(frozen=True)
class BudgetTransfer:
    donor_campaign_id: str
    receiver_campaign_id: str
    amount: Decimal
    donor_efficiency: Decimal
    receiver_efficiency: Decimal
    explanation: str


@dataclass(frozen=True)
class BudgetAllocation:
    campaign_id: str
    before: Decimal
    after: Decimal
    delta: Decimal
    explanation: str


@dataclass(frozen=True)
class BudgetReallocationProposal:
    portfolio_id: str
    status: str
    approval_required: bool
    idempotency_key: str
    total_before: Decimal
    total_after: Decimal
    allocations: tuple[BudgetAllocation, ...]
    transfers: tuple[BudgetTransfer, ...]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _money(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite nonnegative amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite nonnegative amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{name} must be a finite nonnegative amount")
    return amount.quantize(CENT, rounding=ROUND_DOWN)


def propose_budget_reallocation(
    *,
    portfolio_id: str,
    candidates: Iterable[BudgetCandidate],
    target_efficiency: Decimal,
    max_transfer: Decimal,
    as_of: str,
) -> BudgetReallocationProposal:
    """Move budget from below-target campaigns to above-target campaigns.

    Campaign IDs are unique and serve as stable tie breakers. Recommendations
    preserve the portfolio's total daily budget and require human approval.
    """
    if not portfolio_id or not as_of:
        raise ValueError("portfolio_id and as_of are required")
    target = Decimal(str(target_efficiency))
    if not target.is_finite() or target < 0:
        raise ValueError("target_efficiency must be finite and nonnegative")
    transfer_limit = _money(max_transfer, "max_transfer")
    rows = list(candidates)
    ids = [row.campaign_id for row in rows]
    if any(not campaign_id for campaign_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("campaign IDs must be nonempty and unique")
    validated: list[BudgetCandidate] = []
    for row in rows:
        current = _money(row.daily_budget, "daily_budget")
        minimum = _money(row.minimum_budget, "minimum_budget")
        maximum = _money(row.maximum_budget, "maximum_budget")
        efficiency = Decimal(str(row.efficiency))
        if not efficiency.is_finite() or efficiency < 0:
            raise ValueError("efficiency must be finite and nonnegative")
        if minimum > current or current > maximum:
            raise ValueError("current campaign budget must be within its bounds")
        validated.append(BudgetCandidate(row.campaign_id, current, minimum, maximum, efficiency))

    donors = sorted(
        (row for row in validated if row.efficiency < target),
        key=lambda row: (row.efficiency, row.campaign_id),
    )
    receivers = sorted(
        (row for row in validated if row.efficiency > target),
        key=lambda row: (-row.efficiency, row.campaign_id),
    )
    remaining_donor = {row.campaign_id: row.daily_budget - row.minimum_budget for row in donors}
    remaining_receiver = {row.campaign_id: row.maximum_budget - row.daily_budget for row in receivers}
    moved = Decimal("0.00")
    transfers: list[BudgetTransfer] = []
    for donor in donors:
        for receiver in receivers:
            room = transfer_limit - moved
            amount = min(room, remaining_donor[donor.campaign_id], remaining_receiver[receiver.campaign_id])
            amount = amount.quantize(CENT, rounding=ROUND_DOWN)
            if amount <= 0:
                break
            transfers.append(BudgetTransfer(
                donor.campaign_id, receiver.campaign_id, amount, donor.efficiency,
                receiver.efficiency,
                f"Move {amount:.2f} from below-target efficiency {donor.efficiency} "
                f"to above-target efficiency {receiver.efficiency}.",
            ))
            moved += amount
            remaining_donor[donor.campaign_id] -= amount
            remaining_receiver[receiver.campaign_id] -= amount
        if moved >= transfer_limit:
            break

    deltas = {row.campaign_id: Decimal("0.00") for row in validated}
    for transfer in transfers:
        deltas[transfer.donor_campaign_id] -= transfer.amount
        deltas[transfer.receiver_campaign_id] += transfer.amount
    allocations = tuple(
        BudgetAllocation(
            row.campaign_id, row.daily_budget, row.daily_budget + deltas[row.campaign_id],
            deltas[row.campaign_id],
            ("Budget held; no eligible transfer." if deltas[row.campaign_id] == 0 else
             f"Budget {('reduced' if deltas[row.campaign_id] < 0 else 'increased')} by "
             f"{abs(deltas[row.campaign_id]):.2f} within campaign bounds."),
        )
        for row in sorted(validated, key=lambda item: item.campaign_id)
    )
    before = sum((row.daily_budget for row in validated), Decimal("0.00"))
    after = sum((item.after for item in allocations), Decimal("0.00"))
    if before != after:
        raise AssertionError("portfolio budget allocation did not conserve total")
    fingerprint = {
        "portfolio_id": portfolio_id, "as_of": as_of,
        "allocations": [(item.campaign_id, str(item.before), str(item.after)) for item in allocations],
    }
    key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    return BudgetReallocationProposal(
        portfolio_id, "proposed" if transfers else "no_change", bool(transfers), key,
        before, after, allocations, tuple(transfers),
        "Allocation is bounded, conserved, explainable, and awaits human approval."
        if transfers else "No eligible donor and receiver pair had transferable budget.",
    )
