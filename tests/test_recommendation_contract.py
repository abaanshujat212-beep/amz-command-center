import pytest

from services.rules.recommendations import TAXONOMY, build_metadata
from services.rules.rule_catalog import ALL_RULES


@pytest.mark.parametrize("action_type", sorted(TAXONOMY))
def test_every_current_action_maps_to_canonical_contract(action_type):
    item = build_metadata(action_type=action_type, lookback_days=14, metrics={"clicks": 50, "impressions": 2000}, blocked_by=None, objective_snapshot={"status": "not_configured"}, strategy_snapshot={"status": "not_configured"})
    assert item.recommendation_type in set(TAXONOMY.values())
    assert 0 <= item.confidence <= 1
    assert item.expected_behavior["requires_human_approval"] is (action_type != "flag")


def test_missing_economics_and_blocked_confidence_are_explicit():
    item = build_metadata(action_type="set_bid", lookback_days=30, metrics={}, blocked_by="thin_data", objective_snapshot={}, strategy_snapshot={})
    assert item.confidence == 0
    assert item.economic_effect["status"] == "missing"
    assert item.expected_behavior["blocked_by"] == "thin_data"


def test_unknown_action_fails_closed():
    with pytest.raises(ValueError, match="unsupported"):
        build_metadata(action_type="delete_campaign", lookback_days=1, metrics={}, blocked_by=None, objective_snapshot={}, strategy_snapshot={})


def test_every_seeded_rule_emits_an_approved_recommendation_type():
    assert {rule["action"]["type"] for rule in ALL_RULES}.issubset(TAXONOMY)
