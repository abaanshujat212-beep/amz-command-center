"""Deterministic, no-write impact simulation and bounded canary selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Candidate:
    entity_id: str
    current_spend: Decimal
    proposed_spend: Decimal
    protected: bool = False


@dataclass(frozen=True)
class Simulation:
    fingerprint: str
    entity_count: int
    affected_ids: tuple[str, ...]
    protected_ids: tuple[str, ...]
    estimated_spend: Decimal
    estimated_spend_delta: Decimal
    risk_score: Decimal
    exposure_limit: int


def simulate(
    proposed: Mapping[str, object], candidates: Iterable[Candidate], *, exposure_limit: int
) -> Simulation:
    """Replay a frozen candidate set without performing or queueing any mutation."""
    if exposure_limit < 0:
        raise ValueError("exposure_limit must be non-negative")
    rows = sorted(candidates, key=lambda row: row.entity_id)
    protected = tuple(row.entity_id for row in rows if row.protected)
    affected = tuple(
        row.entity_id
        for row in rows
        if not row.protected and row.proposed_spend != row.current_spend
    )
    if len(affected) > exposure_limit:
        raise ValueError(f"aggregate exposure {len(affected)} exceeds limit {exposure_limit}")
    spend = sum((row.current_spend for row in rows if not row.protected), Decimal("0"))
    delta = sum(
        (row.proposed_spend - row.current_spend for row in rows if not row.protected), Decimal("0")
    )
    risk = Decimal("0") if spend == 0 else min(abs(delta) / spend, Decimal("1"))
    payload = {
        "proposed": dict(proposed),
        "candidates": [
            {
                "id": r.entity_id,
                "before": str(r.current_spend),
                "after": str(r.proposed_spend),
                "protected": r.protected,
            }
            for r in rows
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return Simulation(
        fingerprint, len(rows), affected, protected, spend, delta, risk, exposure_limit
    )


def canary_ids(simulation: Simulation, exposure_pct: Decimal) -> tuple[str, ...]:
    if exposure_pct <= 0 or exposure_pct > 100:
        raise ValueError("canary exposure must be between 0 and 100")
    count = int(
        (Decimal(len(simulation.affected_ids)) * exposure_pct / 100).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    return tuple(
        sorted(
            simulation.affected_ids,
            key=lambda value: hashlib.sha256(
                f"{simulation.fingerprint}:{value}".encode()
            ).hexdigest(),
        )[:count]
    )
