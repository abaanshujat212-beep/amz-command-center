import datetime as dt
import gzip
import json

from services.ingest.pipelines.ads_daily import (
    entity_id_for,
    parse_report_payload,
    report_date_for,
)


def test_parse_gzip_json_array_report_payload():
    payload = gzip.compress(json.dumps([{"campaignId": 123, "date": "2026-08-23"}]).encode())
    assert parse_report_payload(payload) == [{"campaignId": 123, "date": "2026-08-23"}]


def test_parse_records_wrapper_report_payload():
    payload = json.dumps({"records": [{"campaignId": "c1"}]}).encode()
    assert parse_report_payload(payload) == [{"campaignId": "c1"}]


def test_campaign_entity_id_uses_campaign_id():
    assert entity_id_for("ads_sp_campaign_daily", {"campaignId": 123}) == "123"


def test_placement_entity_id_includes_placement():
    row = {"campaignId": 123, "placementClassification": "TOP_OF_SEARCH"}
    assert entity_id_for("ads_sp_placement_daily", row) == "123|TOP_OF_SEARCH"


def test_report_date_falls_back_to_requested_day():
    fallback = dt.date(2026, 8, 23)
    assert report_date_for({}, fallback) == fallback
    assert report_date_for({"date": "2026-08-22"}, fallback) == dt.date(2026, 8, 22)
