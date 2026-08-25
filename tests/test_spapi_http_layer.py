import datetime as dt

import httpx
import pytest

from services.ingest.clients.sp_api import SpApiAuthError, SpApiClient, SpApiCredentials, SALES_AND_TRAFFIC


def response(status_code: int, *, json=None, content=None, headers=None, url="https://example.test") -> httpx.Response:
    return httpx.Response(status_code, json=json, content=content, headers=headers, request=httpx.Request("GET", url))


def client() -> SpApiClient:
    c = SpApiClient(SpApiCredentials("client-id", "secret", "refresh-token"), timeout_s=1)
    c._access_token = "token"
    c._access_expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    return c


def test_refresh_access_token_uses_global_token_url(monkeypatch):
    calls = []

    def fake_post(url, data, timeout):
        calls.append((url, data, timeout))
        return response(200, json={"access_token": "new-token", "expires_in": 3600, "refresh_token": "rotated"}, url=url)

    monkeypatch.setattr(httpx, "post", fake_post)
    c = SpApiClient(SpApiCredentials("client-id", "secret", "refresh-token"), timeout_s=1)
    assert c._refresh_access_token() == "new-token"
    assert c.credentials.refresh_token == "rotated"
    assert calls[0][0] == "https://api.amazon.com/auth/o2/token"


def test_refresh_access_token_raises_without_token(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response(200, json={}))
    with pytest.raises(SpApiAuthError):
        SpApiClient(SpApiCredentials("client-id", "secret", "refresh-token"))._refresh_access_token()


def test_call_uses_catalogued_url_and_body(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return response(200, json={"ok": True}, url=url)

    monkeypatch.setattr(httpx, "request", fake_request)
    assert client()._call("sp.orders.list", body={"x": 1}) == {"ok": True}
    assert calls[0][0] == "GET"
    assert calls[0][1] == "https://sellingpartnerapi-eu.amazon.com/orders/v0/orders"
    assert calls[0][2]["json"] == {"x": 1}


def test_create_report_returns_report_id(monkeypatch):
    c = client()
    monkeypatch.setattr(c, "_call", lambda endpoint, body=None, **params: {"reportId": "r-1"})
    monkeypatch.setattr("services.ingest.clients.rate_limit.acquire_report_type", lambda _report_type: None)
    today = dt.date.today()
    assert c.create_report(SALES_AND_TRAFFIC, today - dt.timedelta(days=2), today - dt.timedelta(days=1), {"dateGranularity": "DAY", "asinGranularity": "CHILD"}) == "r-1"


def test_wait_for_report_returns_document_id(monkeypatch):
    c = client()
    monkeypatch.setattr(c, "_call", lambda endpoint, **params: {"processingStatus": "DONE", "reportDocumentId": "doc-1"})
    assert c.wait_for_report("r-1", timeout_s=1) == "doc-1"


def test_download_report_fetches_document_url(monkeypatch):
    c = client()
    monkeypatch.setattr(c, "get_report_document", lambda document_id: {"url": "https://download"})
    calls = []

    def fake_get(url, follow_redirects, timeout):
        calls.append((url, follow_redirects, timeout))
        return response(200, content=b"payload", url=url)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert c.download_report("doc-1") == b"payload"
    assert calls == [("https://download", True, 1)]
