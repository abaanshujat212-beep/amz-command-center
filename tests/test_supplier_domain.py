from datetime import date, timedelta

from services.party.suppliers import quote_freshness


def test_quote_freshness_surfaces_expired_unknown_and_stale_assumptions():
    today = date(2026, 10, 14)
    assert quote_freshness(None, today) == "unknown"
    assert quote_freshness(today - timedelta(days=1), today) == "expired"
    assert quote_freshness(today + timedelta(days=45), today) == "stale_soon"
    assert quote_freshness(today + timedelta(days=91), today) == "current"
