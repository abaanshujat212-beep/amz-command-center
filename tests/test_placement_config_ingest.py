import datetime as dt

from services.ingest.pipelines.placement_config import (
    extract_native_control_row,
    extract_placement_rows,
)


def test_extract_placement_rows_defaults_missing_modifiers_to_zero():
    campaign = {
        "campaignId": "c1",
        "dynamicBidding": {"placementBidding": [{"placement": "PLACEMENT_TOP", "percentage": 35}]},
    }
    rows = extract_placement_rows(campaign)
    assert rows == [
        {"campaign_id": "c1", "placement": "PLACEMENT_TOP", "percentage": 35, "record": campaign},
        {"campaign_id": "c1", "placement": "PLACEMENT_PRODUCT_PAGE", "percentage": 0, "record": campaign},
        {"campaign_id": "c1", "placement": "PLACEMENT_REST_OF_SEARCH", "percentage": 0, "record": campaign},
    ]


def test_extract_placement_rows_skips_campaign_without_id():
    assert extract_placement_rows({"dynamicBidding": {}}) == []


def test_extract_native_control_preserves_supported_strategy_and_source_time():
    row = extract_native_control_row({"campaignId":"c1","lastUpdatedDateTime":"2026-11-20T10:00:00Z","dynamicBidding":{"strategy":"legacyForSales"},"budgetRules":[{"id":"r1"}]}, observed_at=dt.datetime(2026,11,21,tzinfo=dt.timezone.utc))
    assert row is not None
    assert row["bidding_strategy"] == "dynamic_down_only"
    assert row["bidding_strategy_supported"] is True
    assert row["budget_rule_active"] is True
    assert row["source_observed_at"] == dt.datetime(2026,11,20,10,tzinfo=dt.timezone.utc)
    assert len(row["source_fingerprint"]) == 64


def test_extract_native_control_preserves_unknown_strategy_as_unsupported():
    row = extract_native_control_row({"campaignId":"c1","dynamicBidding":{"strategy":"futureMagic"}}, observed_at=dt.datetime.now(dt.timezone.utc))
    assert row is not None
    assert row["bidding_strategy"] == "futureMagic"
    assert row["bidding_strategy_supported"] is False
