"""Every Amazon request must come from the catalog. See ADR 006 and #33.

'The copilot has all the endpoints' is only true if the clients cannot call
anything else. Otherwise the catalog is a document, documents drift, and the
copilot quotes the document with total confidence.

No database and no network: these are import-and-assert tests, so they run in CI
before anything is provisioned.
"""

import datetime as dt
import re
from pathlib import Path

import pytest

from packages.shared import endpoints as ep
from services.ingest.clients import ads_api, rate_limit, sp_api
from services.ingest.pipelines.ads_daily import DATASETS

CLIENT_DIR = Path(__file__).resolve().parents[1] / "services" / "ingest" / "clients"

# A quoted string that begins with '/' is a URL path being built by hand.
QUOTED_PATH = re.compile(r"""['"](/[A-Za-z0-9_{}/.\-]*)['"]""")


def ads_client(region: str = "eu") -> ads_api.AdsClient:
    return ads_api.AdsClient(
        ads_api.AdsCredentials("client-id", "secret", "refresh-token", 987654321),
        region=region,
    )


def sp_client(region: str = "eu") -> sp_api.SpApiClient:
    return sp_api.SpApiClient(
        sp_api.SpApiCredentials("client-id", "secret", "refresh-token"), region=region
    )


# --- one source of truth --------------------------------------------------


def test_no_client_builds_an_uncatalogued_path():
    catalogued = ep.catalogued_paths(ep.Api.SP_API) | ep.catalogued_paths(ep.Api.ADS)
    offenders: list[str] = []
    for path in sorted(CLIENT_DIR.glob("*.py")):
        for literal in QUOTED_PATH.findall(path.read_text()):
            if literal not in catalogued:
                offenders.append(f"{path.name}: {literal}")
    assert offenders == [], (
        "hand-built paths found; add them to packages/shared/endpoints.py and "
        f"call url_for() instead: {offenders}"
    )


def test_lookback_windows_live_in_exactly_one_place():
    assert not hasattr(ads_api, "LOOKBACK_DAYS"), "second lookback table is back"


def test_rate_limits_live_in_exactly_one_place():
    assert not hasattr(rate_limit, "SPAPI_LIMITS")
    assert not hasattr(rate_limit, "ADS_LIMITS")


def test_every_pipeline_dataset_has_a_known_lookback():
    for name, spec in DATASETS.items():
        assert ep.lookback_days(spec.kind) > 0, name


def test_unknown_report_kind_raises_instead_of_defaulting():
    with pytest.raises(ep.UnknownReportKind):
        ep.lookback_days("spSomethingNew")


def test_campaign_and_placement_datasets_share_a_kind_but_not_a_grain():
    campaign = DATASETS["ads_sp_campaign_daily"]
    placement = DATASETS["ads_sp_placement_daily"]
    assert campaign.kind == placement.kind
    assert campaign.group_by != placement.group_by
    assert ep.lookback_days(campaign.kind) == ep.lookback_days(placement.kind)


# --- Amazon's hard walls --------------------------------------------------


def test_ads_client_refuses_a_window_amazon_will_not_serve():
    today = dt.date.today()
    with pytest.raises(ads_api.LookbackExceeded):
        ads_api.AdsClient.check_lookback("sdCampaigns", today - dt.timedelta(days=61))
    ads_api.AdsClient.check_lookback("spCampaigns", today - dt.timedelta(days=61))


def test_sp_client_refuses_history_beyond_two_years():
    with pytest.raises(sp_api.ReportHistoryExceeded):
        sp_api.SpApiClient.check_history(dt.date.today() - dt.timedelta(days=800))


def test_report_request_without_a_grain_is_refused():
    today = dt.date.today()
    with pytest.raises(ValueError) as exc:
        ads_client().create_report(
            "spCampaigns", today - dt.timedelta(days=5), today - dt.timedelta(days=1)
        )
    assert "grain" in str(exc.value)


def test_sales_and_traffic_must_be_requested_at_child_granularity(monkeypatch):
    today = dt.date.today()
    start, end = today - dt.timedelta(days=5), today - dt.timedelta(days=1)
    with pytest.raises(sp_api.AttributionGranularityError):
        sp_client().create_report(
            sp_api.SALES_AND_TRAFFIC,
            start,
            end,
            {"dateGranularity": "DAY", "asinGranularity": "PARENT"},
        )
    with pytest.raises(sp_api.AttributionGranularityError):
        sp_client().create_report(sp_api.SALES_AND_TRAFFIC, start, end, None)

    client = sp_client()
    calls = []

    def fake_call(endpoint, *, body):
        calls.append((endpoint, body))
        return {"reportId": "r-1"}

    monkeypatch.setattr(client, "_call", fake_call)
    monkeypatch.setattr(
        "services.ingest.clients.rate_limit.acquire_report_type",
        lambda _report_type: None,
    )
    assert (
        client.create_report(
            sp_api.SALES_AND_TRAFFIC,
            start,
            end,
            {"dateGranularity": "DAY", "asinGranularity": "CHILD"},
        )
        == "r-1"
    )
    assert calls[0][0] == "sp.reports.create"
    assert calls[0][1]["reportOptions"] == {
        "dateGranularity": "DAY",
        "asinGranularity": "CHILD",
    }


def test_unknown_sp_report_type_is_refused_before_dispatch():
    today = dt.date.today()
    with pytest.raises(sp_api.UnknownReportType):
        sp_client().create_report(
            "GET_A_REPORT_THAT_DOES_NOT_EXIST",
            today - dt.timedelta(days=5),
            today - dt.timedelta(days=1),
        )


# --- blast radius ---------------------------------------------------------


def test_a_read_endpoint_cannot_be_used_to_write():
    with pytest.raises(ads_api.NotAWriteEndpoint):
        ads_client()._call_mutating("ads.keywords.list", body={})


def test_every_action_endpoint_is_declared_mutating():
    for action_type, by_scope in ep.ACTION_ENDPOINTS.items():
        for scope, key in by_scope.items():
            assert ep.endpoint(key).mutates is True, f"{action_type}/{scope} -> {key}"


def test_dry_run_never_reaches_the_dispatch_layer():
    result = ads_client().update_bid("kw-1", 1.25, dry_run=True)
    assert result["status"] == "WOULD_DO"


def test_a_real_bid_update_goes_through_the_catalog(monkeypatch):
    calls = []
    client = ads_client()

    def fake_call(endpoint_key, *, body):
        calls.append((endpoint_key, body))
        return {"ok": True}

    monkeypatch.setattr(client, "_call_mutating", fake_call)
    assert client.update_bid("kw-1", 1.25, dry_run=False) == {"ok": True}
    assert calls == [("ads.keywords.update", {"keywords": [{"keywordId": "kw-1", "bid": 1.25}]})]


def test_placement_modifier_refuses_without_the_current_value():
    with pytest.raises(ValueError):
        ads_client().update_placement_modifier(
            "camp-1", "PLACEMENT_TOP", 30.0, current_percentage=None
        )


def test_off_amazon_placement_cannot_be_adjusted():
    with pytest.raises(ValueError):
        ads_client().update_placement_modifier(
            "camp-1", "OFF_AMAZON", 30.0, current_percentage=0.0
        )


# --- pacing ---------------------------------------------------------------


def test_published_sp_limits_become_buckets_from_the_catalog():
    bucket = rate_limit.limiter_for("sp.reports.create")
    assert bucket is not None
    assert bucket.rate == ep.endpoint("sp.reports.create").rate_limit_rps


def test_ads_endpoints_have_no_invented_rate_limit():
    for endpoint in ep.for_api(ep.Api.ADS):
        assert endpoint.rate_limit_rps is None, endpoint.key
        assert rate_limit.limiter_for(endpoint.key) is None


def test_limiter_for_an_unknown_endpoint_raises():
    with pytest.raises(ep.UnknownEndpoint):
        rate_limit.limiter_for("ads.keywords.updte")


def test_one_bucket_per_endpoint_is_shared():
    assert rate_limit.limiter_for("sp.reports.get") is rate_limit.limiter_for(
        "sp.reports.get"
    )


def test_report_creation_is_not_blindly_retryable():
    assert "sp.reports.create" in rate_limit.NON_RETRYABLE_ENDPOINTS
    assert "ads.reports.create" in rate_limit.NON_RETRYABLE_ENDPOINTS


def test_retry_after_beats_backoff():
    assert rate_limit.backoff_sleep(1, retry_after=42) == 42.0
    assert rate_limit.backoff_sleep(10) <= 120.0


# --- regions --------------------------------------------------------------


def test_urls_follow_the_client_region():
    assert ads_client("eu").url("ads.profiles.list").startswith(
        "https://advertising-api-eu.amazon.com"
    )
    assert ads_client("na").url("ads.profiles.list").startswith(
        "https://advertising-api.amazon.com"
    )
    assert sp_client("eu").url("sp.reports.get", reportId="r-1").endswith(
        "/reports/2021-06-30/reports/r-1"
    )


def test_ads_token_url_is_regional_but_sp_token_url_is_not():
    assert ads_client("eu").token_url == "https://api.amazon.co.uk/auth/o2/token"
    assert ads_client("na").token_url == "https://api.amazon.com/auth/o2/token"
    assert sp_client("eu").token_url == sp_client("na").token_url
