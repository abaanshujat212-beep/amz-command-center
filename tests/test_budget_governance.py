import datetime as dt
from decimal import Decimal

import pytest

from services.config.budget_governance import assess_budget, period_window


def test_daily_window_uses_local_midnight_across_dst():
    window = period_window("daily", "Europe/London", dt.datetime(2026, 3, 29, 12, tzinfo=dt.timezone.utc))
    assert window.start == dt.datetime(2026, 3, 29, 0, tzinfo=dt.timezone.utc)
    assert window.end == dt.datetime(2026, 3, 29, 23, tzinfo=dt.timezone.utc)


def test_week_begins_monday_and_month_rolls_year():
    instant = dt.datetime(2026, 12, 31, 18, tzinfo=dt.timezone.utc)
    week = period_window("weekly", "Asia/Karachi", instant)
    month = period_window("monthly", "Asia/Karachi", instant)
    assert week.start.astimezone(dt.timezone(dt.timedelta(hours=5))).weekday() == 0
    assert month.start.astimezone(dt.timezone(dt.timedelta(hours=5))).date() == dt.date(2026, 12, 1)
    assert month.end.astimezone(dt.timezone(dt.timedelta(hours=5))).date() == dt.date(2027, 1, 1)


def test_projected_spend_fails_closed_at_governance_limit():
    allowed = assess_budget(Decimal("100"), Decimal("80"), Decimal("20"))
    blocked = assess_budget(Decimal("100"), Decimal("80"), Decimal("20.01"))
    assert allowed.allowed and allowed.remaining == Decimal("20")
    assert not blocked.allowed and blocked.reason == "portfolio_budget_limit"
    with pytest.raises(ValueError, match="negative"):
        assess_budget(Decimal("100"), Decimal("-1"), Decimal("5"))
