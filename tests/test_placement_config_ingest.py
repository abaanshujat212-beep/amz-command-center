from services.ingest.pipelines.placement_config import extract_placement_rows


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
