from services.rules.confidence import score_recommendation_confidence
from services.rules.recommendations import build_metadata


def test_confidence_increases_with_volume_freshness_and_stability():
    weak = score_recommendation_confidence(
        clicks=10,
        impressions=20,
        freshness_days=6,
        volatility_cpc_cv=2.0,
        variance_cv=2.0,
        evidence_complete=False,
    )
    strong = score_recommendation_confidence(
        clicks=500,
        impressions=5000,
        freshness_days=0,
        volatility_cpc_cv=0.1,
        variance_cv=0.1,
        evidence_complete=True,
    )
    assert 0 <= weak.score < strong.score <= 100
    assert weak.band == "low"
    assert strong.band == "high"
    assert set(strong.components) == {
        "volume",
        "freshness",
        "variance_stability",
        "cpc_stability",
        "evidence_completeness",
    }


def test_unknown_or_invalid_evidence_never_increases_confidence():
    missing = score_recommendation_confidence(
        clicks=None,
        impressions=-1,
        freshness_days=None,
        volatility_cpc_cv=float("nan"),
        variance_cv=-1,
        evidence_complete=False,
    )
    assert missing.score < 45
    assert missing.band == "low"
    assert "incomplete_evidence" in missing.reasons


def test_low_confidence_is_persisted_as_manual_review_requirement():
    recommendation = build_metadata(
        action_type="set_bid",
        lookback_days=14,
        metrics={"clicks": 10, "impressions": 20, "freshness_days": 1},
        blocked_by=None,
        objective_snapshot={},
        strategy_snapshot={},
    )
    assert recommendation.confidence < 0.75
    assert recommendation.confidence_evidence["score"] < 75
    assert recommendation.expected_behavior["requires_human_approval"] is True


def test_confidence_is_deterministic_and_clamped_to_contract_range():
    args = dict(
        clicks=1e20,
        impressions=1e20,
        freshness_days=0,
        volatility_cpc_cv=0,
        variance_cv=0,
        evidence_complete=True,
    )
    first = score_recommendation_confidence(**args)
    second = score_recommendation_confidence(**args)
    assert first == second
    assert first.score == 100
