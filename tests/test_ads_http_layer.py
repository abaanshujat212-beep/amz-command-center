import datetime as dt

import httpx
import pytest

from services.ingest.clients.ads_api import AdsAuthError, AdsClient, AdsCredentials


def client() -> AdsClient:
    c = AdsClient(AdsCredentials("client-id", "secret", "refresh-token", 123), timeout_s=1)
    c._access_token = "token"
    c._access_expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    return c


def test_refresh_access_token_posts_to_regional_token_url(monkeypatch):
    calls = []

    def fake_post(url, data, timeout):
        calls.append((url, data, timeout))
        return httpx.Response(200, json={"access_token": "new-token", "expires_in": 3600, "refresh_token": "rotated"})

    monkeypatch.setattr(httpx, "post", fake_post)
    c = AdsClient(AdsCredentials("client-id", "secret", "refresh-token", 123), timeout_s=1)
    assert c._refresh_access_token() == "new-token"
    assert c.credentials.refresh_token == "rotated"
    assert calls[0][0] == "https://api.amazon.co.uk/auth/o2/token"
    assert calls[0][1]["grant_type"] == "refresh_token"


def test_refresh_access_token_raises_without_token(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, json={}))
    with pytest.raises(AdsAuthError):
        AdsClient(AdsCredentials("client-id", "secret", "refresh-token"))._refresh_access_token()


def test_call_uses_catalogued_url_and_json_body(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)
    result = client()._call("ads.keywords.list", body={"maxResults": 1})
    assert result == {"ok": True}
    assert calls[0][0] == "POST"
    assert calls[0][1] == "https://advertising-api-eu.amazon.com/sp/keywords/list"
    assert calls[0][2]["json"] == {"maxResults": 1}


def test_call_retries_429_retry_after(monkeypatch):
    responses = [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json={"ok": True})]
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
        return httpx.Response(200, content=b"payload")

    monkeypatch.setattr(httpx, "get", fake_get)
    assert client().download_report("https://download") == b"payload"
    assert calls == [("https://download", True, 1)]
