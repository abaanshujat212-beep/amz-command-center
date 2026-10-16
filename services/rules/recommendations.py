"""Canonical, deterministic recommendation metadata for every rules-engine output."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

TAXONOMY = {
    "set_bid": "bid_adjustment",
    "set_budget": "budget_adjustment",
    "pause": "entity_state",
    "enable": "entity_state",
    "add_negative_exact": "negative_targeting",
    "add_negative_phrase": "negative_targeting",
    "create_keyword": "keyword_harvest",
    "set_placement_modifier": "placement_adjustment",
    "flag": "diagnostic",
}
RISK = {
    "set_bid": "medium",
    "set_budget": "high",
    "pause": "high",
    "enable": "high",
    "add_negative_exact": "high",
    "add_negative_phrase": "high",
    "create_keyword": "medium",
    "set_placement_modifier": "high",
    "flag": "low",
}


@dataclass(frozen=True)
class RecommendationMetadata:
    recommendation_type: str
    confidence: float
    risk: str
    lookback_days: int
    objective_snapshot: dict[str, Any]
    strategy_snapshot: dict[str, Any]
    economic_effect: dict[str, Any]
    expected_behavior: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_metadata(
    *,
    action_type: str,
    lookback_days: int,
    metrics: dict[str, Any],
    blocked_by: str | None,
    objective_snapshot: dict[str, Any],
    strategy_snapshot: dict[str, Any],
) -> RecommendationMetadata:
    if action_type not in TAXONOMY:
        raise ValueError(f"unsupported recommendation action: {action_type}")
    clicks = max(0, int(metrics.get("clicks") or 0))
    impressions = max(0, int(metrics.get("impressions") or 0))
    # Placeholder policy is explicit and deterministic; it is not model confidence.
    confidence = 0.0 if blocked_by else min(0.9, 0.5 + min(clicks / 100, 0.2) + min(impressions / 10000, 0.2))
    break_even = metrics.get("break_even_acos")
    economics = {
        "status": "available" if break_even is not None else "missing",
        "break_even_acos": break_even,
        "acos": metrics.get("acos"),
        "currency": metrics.get("currency"),
    }
    return RecommendationMetadata(
        TAXONOMY[action_type],
        round(confidence, 4),
        RISK[action_type],
        lookback_days,
        objective_snapshot,
        strategy_snapshot,
        economics,
        {
            "action_type": action_type,
            "direction": "diagnostic" if action_type == "flag" else "change",
            "requires_human_approval": action_type != "flag",
            "blocked_by": blocked_by,
        },
    )


def configuration_snapshots(cur, tenant_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    cur.execute(
        """select o.id::text objective_id,o.code objective_code,o.version objective_version,o.mode objective_mode,
                  s.id::text strategy_id,s.code strategy_code,s.version strategy_version,s.mode strategy_mode
             from strategy_version s join objective_version o
               on o.tenant_id=s.tenant_id and o.id=s.objective_version_id
            where s.tenant_id=%s and s.enabled and o.enabled
            order by s.created_at desc limit 1""",
        (tenant_id,),
    )
    row = cur.fetchone()
    if not row:
        missing = {"status": "not_configured"}
        return missing, missing, "unconfigured"
    objective = {key.removeprefix("objective_"): value for key, value in row.items() if key.startswith("objective_")}
    strategy = {key.removeprefix("strategy_"): value for key, value in row.items() if key.startswith("strategy_")}
    return objective, strategy, f"objective:{objective['id']}/strategy:{strategy['id']}"
