"""Transparent PPC health and opportunity scoring.

The scorer deliberately treats unavailable evidence as unavailable.  Missing
components reduce coverage; they never silently become zero and therefore can
never make an account look healthier (or less promising) than the evidence.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class ScoreComponent:
    key: str
    weight: Decimal
    value: Decimal | None
    explanation: str


@dataclass(frozen=True)
class ScoreResult:
    score: Decimal | None
    coverage: Decimal
    components: tuple[dict[str, object], ...]


def calculate_score(components: list[ScoreComponent]) -> ScoreResult:
    if not components:
        raise ValueError("at least one score component is required")
    if any(item.weight <= 0 for item in components):
        raise ValueError("component weights must be positive")
    if any(item.value is not None and not Decimal("0") <= item.value <= Decimal("100") for item in components):
        raise ValueError("component values must be between 0 and 100")

    total_weight = sum((item.weight for item in components), Decimal("0"))
    available = [item for item in components if item.value is not None]
    available_weight = sum((item.weight for item in available), Decimal("0"))
    coverage = (available_weight / total_weight * 100).quantize(Decimal("0.01"))
    score = None
    if available_weight:
        score = (sum((item.value * item.weight for item in available), Decimal("0")) / available_weight).quantize(Decimal("0.01"))
    detail = tuple({"key": item.key, "weight": str(item.weight), "value": None if item.value is None else str(item.value), "available": item.value is not None, "explanation": item.explanation} for item in components)
    return ScoreResult(score=score, coverage=coverage, components=detail)


def calculate_health_and_opportunity(
    evidence: Mapping[str, Decimal | None],
    health_weights: Mapping[str, Decimal],
    opportunity_weights: Mapping[str, Decimal],
) -> tuple[ScoreResult, ScoreResult]:
    def build(weights: Mapping[str, Decimal]) -> list[ScoreComponent]:
        return [ScoreComponent(key, weight, evidence.get(key), "Observed normalized PPC evidence" if evidence.get(key) is not None else "Evidence unavailable") for key, weight in weights.items()]

    return calculate_score(build(health_weights)), calculate_score(build(opportunity_weights))
