import datetime as dt
import gzip
import json
from types import SimpleNamespace

from services.ingest.pipelines.sales_traffic import (
    REPORT_OPTIONS,
    SpConnection,
    normalize_row,
    parse_report_payload,
    persist_rotated_refresh_token,
    plan_dates,
)


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))


def test_sales_traffic_uses_child_daily_options():
    assert REPORT_OPTIONS == {"dateGranularity": "DAY", "asinGranularity": "CHILD"}


def test_parse_sales_and_traffic_payload_shape():
    payload = gzip.compress(json.dumps({"salesAndTrafficByAsin": [{"childAsin": "B001"}]}).encode())
    assert parse_report_payload(payload) == [{"childAsin": "B001"}]


def test_normalize_nested_sales_traffic_row():
    row = {
        "date": "2026-08-23",
        "parentAsin": "PARENT",
        "salesByAsin": {
            "childAsin": "B001",
            "unitsOrdered": 2,
            "orderedProductSales": {"amount": 19.98, "currencyCode": "GBP"},
            "totalOrderItems": 1,
            "unitSessionPercentage": 10,
        },
        "trafficByAsin": {"childAsin": "B001", "sessions": 20, "pageViews": 30, "buyBoxPercentage": 95},
    }
    report_date, entity_id, record = normalize_row(row, dt.date(2026, 8, 22))
    assert report_date == dt.date(2026, 8, 23)
    assert entity_id == "B001"
    assert record["ordered_product_sales"] == 19.98
    assert record["sessions"] == 20


def test_plan_dates_reingests_recent_tail():
    today = dt.date(2026, 8, 24)
    dates = plan_dates(today - dt.timedelta(days=2), today=today)
    assert dates[0] <= today - dt.timedelta(days=14)
    assert dates[-1] == today - dt.timedelta(days=1)


def test_persist_rotated_refresh_token_writes_ciphertext(monkeypatch):
    monkeypatch.setenv("KEK_BASE64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    conn = FakeConn()
    connection = SpConnection("conn-1", "eu", "client-id", "secret", "old-token")
    client = SimpleNamespace(credentials=SimpleNamespace(refresh_token="rotated-token"))
    persist_rotated_refresh_token(conn, connection, client)
    assert conn.calls
    sql, params = conn.calls[0]
    assert "refresh_token_encrypted" in sql
    assert params[1] == 1
    assert params[2] == "conn-1"
    assert params[0] != b"rotated-token"


def test_persist_rotated_refresh_token_skips_unchanged_token(monkeypatch):
    monkeypatch.setenv("KEK_BASE64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    conn = FakeConn()
    connection = SpConnection("conn-1", "eu", "client-id", "secret", "same-token")
    client = SimpleNamespace(credentials=SimpleNamespace(refresh_token="same-token"))
    persist_rotated_refresh_token(conn, connection, client)
    assert conn.calls == []
