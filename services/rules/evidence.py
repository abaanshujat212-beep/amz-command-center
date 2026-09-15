"""Immutable proposal-time evidence used for apply-time guardrail checks."""

from __future__ import annotations

from services.rules.freshness import SourceFreshness

CONTEXT_VERSION = 1


def build_guardrail_context(
    *,
    entities_evaluated: int,
    entities_matched: int,
    min_clicks: int,
    min_impressions: int,
    freshness: SourceFreshness,
) -> dict:
    """Return a versioned, JSON-serializable snapshot without inferred values."""
    return {
        "version": CONTEXT_VERSION,
        "entities_evaluated": int(entities_evaluated),
        "entities_matched": int(entities_matched),
        "min_clicks": int(min_clicks),
        "min_impressions": int(min_impressions),
        "source_freshness": freshness.as_dict(),
    }
