import datetime as dt
import gzip
import json

from services.ingest.pipelines.sales_traffic import (
    REPORT_OPTIONS,
    normalize_row,
    parse_report_payload,
    plan_dates,
)


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
