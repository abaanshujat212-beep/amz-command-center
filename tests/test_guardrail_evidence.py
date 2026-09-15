import datetime as dt

from services.rules.evidence import build_guardrail_context
from services.rules.freshness import FreshnessState, SourceFreshness


def test_guardrail_context_preserves_typed_denominator_thresholds_and_freshness():
    loaded_at = dt.datetime(2026, 9, 15, 7, 0, tzinfo=dt.timezone.utc)
    freshness = SourceFreshness(
        state=FreshnessState.FRESH,
        datasets=("ads_sp_keyword_daily",),
        data_through=dt.date(2026, 9, 12),
        data_loaded_at=loaded_at,
    )

    context = build_guardrail_context(
        entities_evaluated=25,
        entities_matched=4,
        min_clicks=15,
        min_impressions=500,
        freshness=freshness,
    )

    assert context == {
        "version": 1,
        "entities_evaluated": 25,
        "entities_matched": 4,
        "min_clicks": 15,
        "min_impressions": 500,
        "source_freshness": {
            "state": FreshnessState.FRESH,
            "datasets": ("ads_sp_keyword_daily",),
            "data_through": dt.date(2026, 9, 12),
            "data_loaded_at": loaded_at,
            "detail": None,
        },
    }
