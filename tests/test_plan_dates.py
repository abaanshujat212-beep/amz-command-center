"""Backfill / incremental planning tests — pure logic, no Amazon calls."""

import datetime as dt

from services.ingest.pipelines.ads_daily import find_gaps, plan_dates, rules_safe_date

TODAY = dt.date(2026, 8, 20)


def test_first_run_backfills_full_window():
    dates = plan_dates(None, today=TODAY)
    assert dates[0] == TODAY - dt.timedelta(days=95)
    assert dates[-1] == TODAY - dt.timedelta(days=1)
    assert dates == sorted(dates), "oldest day must be fetched first"


def test_incremental_includes_reingest_tail():
    dates = plan_dates(TODAY - dt.timedelta(days=2), today=TODAY)
    # restatement means recent days are refetched, not trusted once
    assert dates[0] <= TODAY - dt.timedelta(days=14)
    assert dates[-1] == TODAY - dt.timedelta(days=1)


def test_never_requests_beyond_lookback():
    dates = plan_dates(dt.date(2020, 1, 1), today=TODAY)
    assert dates[0] >= TODAY - dt.timedelta(days=95)


def test_nothing_to_do_when_current():
    assert plan_dates(TODAY - dt.timedelta(days=1), today=TODAY, reingest_days=1) == []


def test_gap_detection_oldest_first():
    expected = [TODAY - dt.timedelta(days=i) for i in (5, 4, 3, 2)]
    present = {TODAY - dt.timedelta(days=4)}
    gaps = find_gaps(expected, present)
    assert gaps[0] == TODAY - dt.timedelta(days=5)
    assert len(gaps) == 3


def test_rules_lag_is_three_days():
    assert rules_safe_date(TODAY) == dt.date(2026, 8, 17)
