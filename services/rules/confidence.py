"""Deterministic, explainable confidence scoring for optimizer recommendations."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ConfidenceScore:
    score: int
    band: str
    components: Mapping[str, float]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        return result


def score_recommendation_confidence(
    *,
    clicks: int | float | None,
    impressions: int | float | None,
    freshness_days: int | float | None,
    volatility_cpc_cv: int | float | None = None,
    variance_cv: int | float | None = None,
    evidence_complete: bool = True,
) -> ConfidenceScore:
    """Score evidence quality from 0 to 100; never treats score as approval.

    Missing optional variance or stability evidence receives a neutral 0.70
    factor. Invalid counts/freshness fail toward zero; invalid variability is
    conservatively treated as maximally unstable.
    """
    click_count = _valid_nonnegative(clicks)
    impression_count = _valid_nonnegative(impressions)
    freshness = _valid_nonnegative(freshness_days)
    volume = min(1.0, math.sqrt(min(click_count or 0, impression_count or 0) / 100.0))
    fresh = max(0.0, 1.0 - (freshness / 7.0)) if freshness is not None else 0.0
    variance = _stability(variance_cv)
    cpc_stability = _stability(volatility_cpc_cv)
    completeness = 1.0 if evidence_complete else 0.0
    # Weighted blend: a missing/weak core dimension lowers confidence without
    # allowing excellent volume to conceal stale evidence.
    raw = 100 * (
        0.40 * volume + 0.25 * fresh + 0.15 * variance + 0.10 * cpc_stability + 0.10 * completeness
    )
    score = round(max(0.0, min(100.0, raw)))
    band = "high" if score >= 75 else "medium" if score >= 45 else "low"
    reasons = []
    if volume < 0.5:
        reasons.append("limited_volume")
    if freshness is None or freshness > 3:
        reasons.append("stale_or_unknown_freshness")
    if variance < 0.5:
        reasons.append("high_variance_or_unknown")
    if cpc_stability < 0.5:
        reasons.append("unstable_or_unknown_cpc")
    if not evidence_complete:
        reasons.append("incomplete_evidence")
    return ConfidenceScore(
        score=score,
        band=band,
        components={
            "volume": round(volume, 4),
            "freshness": round(fresh, 4),
            "variance_stability": round(variance, 4),
            "cpc_stability": round(cpc_stability, 4),
            "evidence_completeness": completeness,
        },
        reasons=tuple(reasons),
    )


def _valid_nonnegative(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _stability(cv: Any) -> float:
    if cv is None:
        return 0.70
    value = _valid_nonnegative(cv)
    if value is None:
        return 0.0
    return 1.0 / (1.0 + value)
