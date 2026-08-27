import datetime as dt

from services.ingest.pipelines.sqp import parse_row


def test_parse_sqp_row_normalizes_query_and_numbers():
    row = parse_row({
        "asin": "B001",
        "search_query": " Hook Tape ",
        "report_date": "2026-08-01",
        "query_volume": "12,000",
        "clicks": "70",
    })
    assert row["asin"] == "B001"
    assert row["search_query"] == "hook tape"
    assert row["report_date"] == dt.date(2026, 8, 1)
    assert row["query_volume"] == 12000
    assert row["clicks"] == 70


def test_parse_sqp_row_requires_identity_fields():
    try:
        parse_row({"asin": "B001"})
    except ValueError as exc:
        assert "required" in str(exc)
    else:
        raise AssertionError("expected ValueError")
