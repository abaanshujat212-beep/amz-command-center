"""Translate bounded Top-of-Search plans into the canonical review contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from packages.shared.action_capabilities import capability
from services.rules.recommendations import build_metadata
from services.rules.tos_optimizer import TopOfSearchPlan


def review_top_of_search(
    plan: TopOfSearchPlan,
    *,
    now: datetime,
    objective_snapshot: dict[str, Any],
    strategy_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Serialize for review only, not as outbox entries or approved actions."""
    evidence = plan.evidence
    if evidence is None or not plan.candidates:
        return []
    metrics = {
        "currency": evidence.currency,
        "campaign_id": evidence.campaign_id,
        "keyword_id": evidence.keyword_id,
        "profile_id": evidence.profile_id,
        "clicks": evidence.top_clicks,
        "impressions": evidence.top_impressions,
        "orders": evidence.top_orders,
        "acos": float(evidence.top_spend / evidence.top_sales),
        "impression_share": float(evidence.impression_share),
        "break_even_acos": float(evidence.break_even_acos),
        "freshness_days": (now - evidence.loaded_at).total_seconds() / 86400,
        "window_start": evidence.window_start.isoformat(),
        "data_through": evidence.window_end.isoformat(),
        "loaded_at": evidence.loaded_at.isoformat(),
    }
    records = []
    for candidate in plan.candidates:
        capabilities = capability(candidate.entity_type, candidate.action_type)
        if not capabilities.recommendation_supported:
            continue
        metadata = build_metadata(
            action_type=candidate.action_type,
            lookback_days=max(1, (evidence.window_end - evidence.window_start).days),
            metrics=metrics,
            blocked_by=None,
            objective_snapshot=objective_snapshot,
            strategy_snapshot=strategy_snapshot,
        ).as_dict()
        metadata["economic_effect"].update(
            {
                "effective_acos_ceiling": str(plan.effective_acos_ceiling),
                "combined_top_bid": str(plan.combined_top_bid),
                "estimated_incremental_daily_spend": str(plan.estimated_incremental_daily_spend),
                "estimation_basis": "peak_observed_keyword_clicks_with_full_bid_delta_as_cpc",
            }
        )
        metadata["expected_behavior"].update(
            {
                "proposal_only": True,
                "automation_enabled": False,
                "executable": False,
                "approval_capability_registered": capabilities.approval_supported,
            }
        )
        before_value: dict[str, Any] = {"value": float(candidate.before_value)}
        after_value: dict[str, Any] = {"value": float(candidate.after_value)}
        if candidate.placement:
            before_value["placement"] = candidate.placement
            after_value["placement"] = candidate.placement
        records.append(
            {
                "tenant_id": evidence.tenant_id,
                "entity_type": candidate.entity_type,
                "entity_id": candidate.entity_id,
                "action_type": candidate.action_type,
                "before_value": before_value,
                "after_value": after_value,
                "reason_text": candidate.reason,
                "metrics_snapshot": dict(metrics),
                **metadata,
            }
        )
    return records
