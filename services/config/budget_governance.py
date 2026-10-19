"""Deterministic portfolio budget period resolution and proposal enforcement."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class PeriodWindow:
    start: dt.datetime
    end: dt.datetime


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    remaining: Decimal
    projected: Decimal
    reason: str | None


def period_window(period: str, timezone: str, instant: dt.datetime) -> PeriodWindow:
    if instant.tzinfo is None:
        raise ValueError("instant must include a timezone")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA name") from exc
    local = instant.astimezone(zone)
    day = local.date()
    if period == "daily":
        start_day = day
        end_day = day + dt.timedelta(days=1)
    elif period == "weekly":
        start_day = day - dt.timedelta(days=day.weekday())
        end_day = start_day + dt.timedelta(days=7)
    elif period == "monthly":
        start_day = day.replace(day=1)
        end_day = (start_day.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    else:
        raise ValueError("period must be daily, weekly or monthly")
    return PeriodWindow(
        dt.datetime.combine(start_day, dt.time.min, zone).astimezone(dt.timezone.utc),
        dt.datetime.combine(end_day, dt.time.min, zone).astimezone(dt.timezone.utc),
    )


def assess_budget(limit: Decimal, spent: Decimal, proposed: Decimal) -> BudgetDecision:
    if min(limit, spent, proposed) < 0:
        raise ValueError("budget values cannot be negative")
    projected = spent + proposed
    remaining = max(Decimal("0"), limit - spent)
    allowed = projected <= limit
    return BudgetDecision(allowed, remaining, projected, None if allowed else "portfolio_budget_limit")


def resolve_limit(conn, tenant_id: str, portfolio_id: str, period: str, local_day: dt.date):
    """Portfolio override wins; account fallback is explicit and tenant scoped."""
    return conn.execute(
        """select * from portfolio_budget_limit where tenant_id=%s and period_type=%s
             and ((scope_type='portfolio' and scope_id=%s) or (scope_type='account' and scope_id='*'))
             and effective_from<=%s and(effective_to is null or effective_to>=%s)
             order by case scope_type when 'portfolio' then 0 else 1 end limit 1""",
        (tenant_id, period, portfolio_id, local_day, local_day),
    ).fetchone()
