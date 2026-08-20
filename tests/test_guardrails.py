"""Guardrail tests. These are the tests that keep a client's account safe."""

import datetime as dt

import pytest

from services.rules.guardrails import (
    Guard,
    Proposal,
    RunContext,
    TenantGuardConfig,
    check,
    clamp_change,
)

NOW = dt.datetime(2026, 8, 20, 9, 0, tzinfo=dt.timezone.utc)
LIVE = TenantGuardConfig(automation_enabled=True, dry_run=False)


def ctx(**kw) -> RunContext:
    base = dict(
        now=NOW,
        data_through=dt.date(2026, 8, 17),   # exactly T-3, settled
        data_loaded_at=NOW - dt.timedelta(hours=6),
        entities_evaluated=100,
        entities_matched=5,
    )
    base.update(kw)
    return RunContext(**base)


def bid(before: float, after: float, clicks: int = 40) -> Proposal:
    return Proposal("keyword", "kw-1", "set_bid", before, after, clicks=clicks, impressions=5000)


# ------------------------------------------------------------------ clamping
def test_clamps_extreme_increase_to_25_percent():
    value, clamped, note = clamp_change(1.00, 3.00, LIVE)
    assert clamped and value == pytest.approx(1.25)
    assert "clamped" in note


def test_clamps_extreme_decrease():
    value, clamped, _ = clamp_change(1.00, 0.10, LIVE)
    assert clamped and value == pytest.approx(0.75)


def test_small_change_passes_untouched():
    value, clamped, _ = clamp_change(1.00, 1.10, LIVE)
    assert not clamped and value == pytest.approx(1.10)


def test_200_percent_proposal_is_clamped_and_logged():
    d = check(bid(1.00, 3.00), LIVE, ctx())
    assert d.allowed and d.clamped and d.value == pytest.approx(1.25)
    assert d.notes, "clamping must be recorded, never silent"


def test_bounds_applied_after_clamp():
    cfg = TenantGuardConfig(automation_enabled=True, dry_run=False, max_bid=1.10)
    d = check(bid(1.00, 1.25), cfg, ctx())
    assert d.value == pytest.approx(1.10) and d.clamped


def test_min_bid_floor():
    cfg = TenantGuardConfig(automation_enabled=True, dry_run=False, min_bid=0.50)
    d = check(bid(0.60, 0.45), cfg, ctx())
    assert d.value == pytest.approx(0.50)


# ---------------------------------------------------------------- hard stops
def test_kill_switch_blocks_everything():
    d = check(bid(1.00, 1.10), TenantGuardConfig(automation_enabled=False), ctx())
    assert not d.allowed and d.blocked_by is Guard.KILL_SWITCH


def test_dry_run_allows_but_marks_would_do():
    cfg = TenantGuardConfig(automation_enabled=True, dry_run=True)
    d = check(bid(1.00, 1.10), cfg, ctx())
    assert d.allowed and any("WOULD_DO" in n for n in d.notes)


def test_stale_data_blocks():
    d = check(bid(1.00, 1.10), LIVE, ctx(data_loaded_at=NOW - dt.timedelta(hours=72)))
    assert d.blocked_by is Guard.STALE_DATA


def test_unsettled_data_blocks():
    d = check(bid(1.00, 1.10), LIVE, ctx(data_through=dt.date(2026, 8, 19)))
    assert d.blocked_by is Guard.UNSETTLED_DATA


def test_thin_data_blocks():
    thin = Proposal("keyword", "kw-2", "set_bid", 1.00, 1.10, clicks=3, impressions=40)
    assert check(thin, LIVE, ctx()).blocked_by is Guard.THIN_DATA


def test_cooldown_blocks_second_change():
    d = check(bid(1.00, 1.10), LIVE, ctx(last_applied_at=NOW - dt.timedelta(days=1)))
    assert d.blocked_by is Guard.COOLDOWN


def test_cooldown_expired_allows():
    d = check(bid(1.00, 1.10), LIVE, ctx(last_applied_at=NOW - dt.timedelta(days=4)))
    assert d.allowed


def test_blast_radius_halts_run():
    d = check(bid(1.00, 1.10), LIVE, ctx(entities_evaluated=100, entities_matched=45))
    assert d.blocked_by is Guard.BLAST_RADIUS


def test_blast_radius_ignored_on_small_samples():
    d = check(bid(1.00, 1.10), LIVE, ctx(entities_evaluated=5, entities_matched=4))
    assert d.allowed, "4 of 5 entities is not a blast radius, it is a small account"


def test_daily_change_limit():
    d = check(bid(1.00, 1.10), LIVE, ctx(changes_applied_today=50))
    assert d.blocked_by is Guard.DAILY_CHANGE_LIMIT


def test_daily_budget_increase_cap():
    budget = Proposal("campaign", "c-1", "set_budget", 20.0, 24.0, clicks=500, impressions=90000)
    d = check(budget, LIVE, ctx(budget_increase_today=48.0))
    assert d.blocked_by is Guard.DAILY_BUDGET_LIMIT


def test_budget_increase_within_cap_allowed():
    budget = Proposal("campaign", "c-1", "set_budget", 20.0, 24.0, clicks=500, impressions=90000)
    d = check(budget, LIVE, ctx(budget_increase_today=0.0))
    assert d.allowed and d.value == pytest.approx(24.0)
