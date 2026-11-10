import datetime as dt

import httpx
import pytest

from services.ingest.clients.ads_api import AdsAuthError, AdsClient, AdsCredentials


def client() -> AdsClient:
    c = AdsClient(AdsCredentials("client-id", "secret", "refresh-token", 123), timeout_s=1)
    c._access_token = "token"
    c._access_expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    return c


def response(status_code: int, *, json=None, content=None, headers=None, url="https://example.test") -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(status_code, json=json, content=content, headers=headers, request=request)


def test_refresh_access_token_posts_to_regional_token_url(monkeypatch):
    calls = []

    def fake_post(url, data, timeout):
        calls.append((url, data, timeout))
        return response(200, json={"access_token": "new-token", "expires_in": 3600, "refresh_token": "rotated"}, url=url)

    monkeypatch.setattr(httpx, "post", fake_post)
    c = AdsClient(AdsCredentials("client-id", "secret", "refresh-token", 123), timeout_s=1)
    assert c._refresh_access_token() == "new-token"
    assert c.credentials.refresh_token == "rotated"
    assert calls[0][0] == "https://api.amazon.co.uk/auth/o2/token"
    assert calls[0][1]["grant_type"] == "refresh_token"


def test_refresh_access_token_raises_without_token(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response(200, json={}))
    with pytest.raises(AdsAuthError):
        AdsClient(AdsCredentials("client-id", "secret", "refresh-token"))._refresh_access_token()


def test_call_uses_catalogued_url_and_json_body(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return response(200, json={"ok": True}, url=url)

    monkeypatch.setattr(httpx, "request", fake_request)
    result = client()._call("ads.keywords.list", body={"maxResults": 1})
    assert result == {"ok": True}
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://advertising-api-eu.amazon.com/sp/keywords/list"
    assert calls[0][2]["json"] == {"maxResults": 1}
    assert calls[0][2]["headers"]["Content-Type"] == "application/vnd.spKeyword.v3+json"
    assert calls[0][2]["headers"]["Accept"] == "application/vnd.spKeyword.v3+json"


def test_exact_keyword_duplicate_check_scans_all_pages(monkeypatch):
    c = client()
    calls = []
    pages = [
        {"keywords": [{"keywordText": "other", "matchType": "EXACT", "state": "ENABLED"}], "nextToken": "next"},
        {"keywords": [{"keywordText": "Hook   and Loop Tape", "matchType": "EXACT", "state": "PAUSED"}]},
    ]

    def fake_call(endpoint, body=None, **params):
        calls.append((endpoint, body))
        return pages.pop(0)

    monkeypatch.setattr(c, "_call", fake_call)
    assert c.exact_keyword_exists("g-1", "hook and loop tape")
    assert calls == [
        ("ads.keywords.list", {"maxResults": 500, "adGroupIdFilter": {"include": ["g-1"]}}),
        ("ads.keywords.list", {"maxResults": 500, "adGroupIdFilter": {"include": ["g-1"]}, "nextToken": "next"}),
    ]


def test_create_keyword_uses_exact_v3_payload_and_preflights_duplicate(monkeypatch):
    c = client()
    calls = []

    def fake_call(endpoint, body=None, **params):
        calls.append((endpoint, body))
        return {"keywords": []}

    monkeypatch.setattr(c, "_call", fake_call)
    monkeypatch.setattr(c, "_call_mutating", fake_call)
    monkeypatch.setattr(c, "exact_keyword_exists", lambda ad_group_id, term: False)
    result = c.create_keyword(
        campaign_id="c-1", ad_group_id="g-1", keyword_text=" hook tape ", bid=0.42,
        match_type="exact", dry_run=False,
    )
    assert result == {"keywords": []}
    assert calls == [("ads.keywords.create", {"keywords": [{
        "campaignId": "c-1", "adGroupId": "g-1", "keywordText": "hook tape",
        "matchType": "EXACT", "state": "ENABLED", "bid": 0.42,
    }]})]


def test_create_keyword_duplicate_preflight_prevents_write(monkeypatch):
    c = client()
    writes = []
    monkeypatch.setattr(c, "exact_keyword_exists", lambda *_: True)
    monkeypatch.setattr(c, "_call_mutating", lambda *args, **kwargs: writes.append(args))
    with pytest.raises(RuntimeError, match="already exists"):
        c.create_keyword(campaign_id="c-1", ad_group_id="g-1", keyword_text="hook tape", bid=0.42, dry_run=False)
    assert writes == []


def test_create_keyword_rejects_partial_api_errors(monkeypatch):
    c = client()
    monkeypatch.setattr(c, "exact_keyword_exists", lambda *_: False)
    monkeypatch.setattr(c, "_call_mutating", lambda *args, **kwargs: {"keywords": {"error": [{"message": "invalid bid"}]}})
    with pytest.raises(RuntimeError, match="rejected keyword creation"):
        c.create_keyword(campaign_id="c-1", ad_group_id="g-1", keyword_text="hook tape", bid=0.42, dry_run=False)


@pytest.mark.parametrize("bid", [0, -0.1, float("inf"), float("nan")])
def test_create_keyword_requires_finite_positive_bid(bid):
    with pytest.raises(ValueError, match="finite positive"):
        client().create_keyword(
            campaign_id="c-1", ad_group_id="g-1", keyword_text="hook tape", bid=bid
        )


def test_target_bid_never_uses_keyword_endpoint(monkeypatch):
    c = client()
    calls = []

    def fake_call(endpoint, body=None, **params):
        calls.append((endpoint, body))
        if endpoint == "ads.targets.list":
            return {"targets": [{"targetId": "t-1", "bid": 0.75}]}
        return {"ok": True}

    monkeypatch.setattr(c, "_call", fake_call)
    monkeypatch.setattr(c, "_call_mutating", fake_call)
    assert c.target_bid("t-1") == {"value": 0.75}
    c.update_target_bid("t-1", 0.9, dry_run=False)
    assert calls == [
        ("ads.targets.list", {"maxResults": 500, "targetIdFilter": {"include": ["t-1"]}}),
        ("ads.targets.update", {"targetingClauses": [{"targetId": "t-1", "bid": 0.9}]}),
    ]
    assert all("keywords" not in endpoint for endpoint, _ in calls)


def test_campaign_status_read_and_update_use_campaign_contract(monkeypatch):
    c = client()
    calls = []

    def fake_call(endpoint, body=None, **params):
        calls.append((endpoint, body))
        if endpoint == "ads.campaigns.list":
            return {"campaigns": [{"campaignId": "c-1", "state": "enabled"}]}
        return {"ok": True}

    monkeypatch.setattr(c, "_call", fake_call)
    monkeypatch.setattr(c, "_call_mutating", fake_call)
    assert c.campaign_status("c-1") == {"value": "ENABLED"}
    assert c.update_campaign_status("c-1", "PAUSED", dry_run=False) == {"ok": True}
    assert calls == [
        ("ads.campaigns.list", {"maxResults": 500, "campaignIdFilter": {"include": ["c-1"]}}),
        ("ads.campaigns.update", {"campaigns": [{"campaignId": "c-1", "state": "PAUSED"}]}),
    ]


def test_campaign_budget_read_and_update_use_campaign_contract(monkeypatch):
    c = client()
    calls = []

    def fake_call(endpoint, body=None, **params):
        calls.append((endpoint, body))
        if endpoint == "ads.campaigns.list":
            return {"campaigns": [{"campaignId": "c-1", "budget": {"budget": 20.0}}]}
        return {"ok": True}

    monkeypatch.setattr(c, "_call", fake_call)
    monkeypatch.setattr(c, "_call_mutating", fake_call)
    assert c.campaign_budget("c-1") == {"value": 20.0}
    assert c.update_campaign_budget("c-1", 24.0, dry_run=False) == {"ok": True}
    assert calls == [
        ("ads.campaigns.list", {"maxResults": 500, "campaignIdFilter": {"include": ["c-1"]}}),
        ("ads.campaigns.update", {"campaigns": [{"campaignId": "c-1", "budget": {"budget": 24.0}}]}),
    ]


@pytest.mark.parametrize(
    ("entity_type", "entity_id", "list_endpoint", "rows", "expected_update"),
    [
        ("ad_group", "g-1", "ads.adGroups.list", {"adGroups": [{"adGroupId": "g-1", "state": "paused"}]}, ("ads.adGroups.update", {"adGroups": [{"adGroupId": "g-1", "state": "ENABLED"}]})),
        ("keyword", "k-1", "ads.keywords.list", {"keywords": [{"keywordId": "k-1", "state": "enabled"}]}, ("ads.keywords.update", {"keywords": [{"keywordId": "k-1", "state": "ENABLED"}]})),
        ("target", "t-1", "ads.targets.list", {"targets": [{"targetId": "t-1", "state": "paused"}]}, ("ads.targets.update", {"targetingClauses": [{"targetId": "t-1", "state": "ENABLED"}]})),
    ],
)
def test_entity_status_read_and_update_contract(monkeypatch, entity_type, entity_id, list_endpoint, rows, expected_update):
    c = client()
    calls = []

    def fake_call(endpoint, body=None, **params):
        calls.append((endpoint, body))
        return rows if endpoint == list_endpoint else {"ok": True}

    monkeypatch.setattr(c, "_call", fake_call)
    monkeypatch.setattr(c, "_call_mutating", fake_call)
    assert c.entity_status(entity_type, entity_id) == {"value": rows[next(iter(rows))][0]["state"].upper()}
    assert c.update_entity_status(entity_type, entity_id, "ENABLED", dry_run=False) == {"ok": True}
    assert calls[-1] == expected_update


def test_ad_group_default_bid_read_and_update_contract(monkeypatch):
    c = client()
    calls = []

    def fake_call(endpoint, body=None, **params):
        calls.append((endpoint, body))
        if endpoint == "ads.adGroups.list":
            return {"adGroups": [{"adGroupId": "g-1", "defaultBid": 0.75}]}
        return {"ok": True}

    monkeypatch.setattr(c, "_call", fake_call)
    monkeypatch.setattr(c, "_call_mutating", fake_call)
    assert c.ad_group_default_bid("g-1") == {"value": 0.75}
    assert c.update_ad_group_default_bid("g-1", 0.9, dry_run=False) == {"ok": True}
    assert calls[-1] == ("ads.adGroups.update", {"adGroups": [{"adGroupId": "g-1", "defaultBid": 0.9}]})


def test_campaign_status_update_rejects_unknown_states():
    with pytest.raises(ValueError, match="ENABLED or PAUSED"):
        client().update_campaign_status("c-1", "ARCHIVED", dry_run=False)


def test_campaign_budget_update_rejects_nonpositive_amount():
    with pytest.raises(ValueError, match="greater than zero"):
        client().update_campaign_budget("c-1", 0, dry_run=False)


def test_call_retries_429_retry_after(monkeypatch):
    responses = [
        response(429, headers={"Retry-After": "0"}),
        response(200, json={"ok": True}),
    ]
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    assert client()._call("ads.keywords.list", body={}) == {"ok": True}


def test_create_report_returns_report_id(monkeypatch):
    c = client()
    monkeypatch.setattr(c, "_call", lambda endpoint, body=None, **params: {"reportId": "r-1"})
    today = dt.date.today()
    assert c.create_report("spCampaigns", today - dt.timedelta(days=2), today - dt.timedelta(days=1), ("campaign",)) == "r-1"


def test_wait_for_report_returns_download_url(monkeypatch):
    c = client()
    monkeypatch.setattr(c, "_call", lambda endpoint, **params: {"status": "SUCCESS", "url": "https://download"})
    assert c.wait_for_report("r-1", timeout_s=1) == "https://download"


def test_download_report_follows_redirects(monkeypatch):
    calls = []

    def fake_get(url, follow_redirects, timeout):
        calls.append((url, follow_redirects, timeout))
        return response(200, content=b"payload", url=url)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert client().download_report("https://download") == b"payload"
    assert calls == [("https://download", True, 1)]
