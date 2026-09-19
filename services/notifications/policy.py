"""Fail-closed notification preference and delivery-policy decisions."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ALLOWED_EVENT_TYPES = frozenset(
    {
        "auth_expiring", "auth_expired", "pipeline_failed", "data_stale",
        "blast_radius_halt", "budget_guard", "action_failed", "economics_incomplete",
        "low_inventory", "projected_stockout", "reorder_due", "inbound_delayed",
        "excess_stock", "unusual_demand",
    }
)
ALLOWED_SEVERITIES = frozenset({"info", "warning", "critical"})
ALLOWED_CHANNELS = frozenset({"in_app", "email", "whatsapp", "sms"})
ALLOWED_MODES = frozenset({"immediate", "digest"})
EXTERNAL_CHANNELS = ALLOWED_CHANNELS - {"in_app"}
DIGEST_INTERVALS = frozenset({60, 1440})

IMMEDIATE = "IMMEDIATE"
BLOCKED_DISABLED = "BLOCKED_DISABLED"
BLOCKED_CONSENT = "BLOCKED_CONSENT"
BLOCKED_CONFIGURATION = "BLOCKED_CONFIGURATION"
DEFERRED_QUIET_HOURS = "DEFERRED_QUIET_HOURS"
QUEUED_DIGEST = "QUEUED_DIGEST"
ELIGIBLE = "ELIGIBLE"


@dataclass(frozen=True)
class RoutePreference:
    event_type: str
    channel: str
    enabled: bool
    delivery_mode: str = "immediate"
    digest_interval_minutes: int | None = None
    timezone: str = "UTC"
    quiet_start: dt.time | None = None
    quiet_end: dt.time | None = None
    critical_bypass: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    status: str
    eligible_at: dt.datetime | None = None


def _validate(preference: RoutePreference) -> ZoneInfo:
    if preference.event_type != "*" and preference.event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError("unsupported notification event type")
    if preference.channel not in ALLOWED_CHANNELS:
        raise ValueError("unsupported notification channel")
    if preference.delivery_mode not in ALLOWED_MODES:
        raise ValueError("unsupported notification delivery mode")
    if (preference.quiet_start is None) != (preference.quiet_end is None):
        raise ValueError("quiet hours require both start and end")
    if preference.quiet_start is not None and preference.quiet_start == preference.quiet_end:
        raise ValueError("quiet hour start and end must differ")
    if preference.delivery_mode == "digest":
        if preference.digest_interval_minutes not in DIGEST_INTERVALS:
            raise ValueError("unsupported digest interval")
    elif preference.digest_interval_minutes is not None:
        raise ValueError("immediate delivery cannot have a digest interval")
    if preference.channel == "in_app" and (
        not preference.enabled or preference.delivery_mode != "immediate"
        or preference.quiet_start is not None or preference.critical_bypass
    ):
        raise ValueError("in-app routing must remain enabled and immediate")
    try:
        return ZoneInfo(preference.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid notification timezone") from exc


def default_preference(event_type: str, channel: str) -> RoutePreference:
    preference = RoutePreference(event_type=event_type, channel=channel, enabled=channel == "in_app")
    _validate(preference)
    return preference


def _cell(row, name: str, index: int):
    return row[name] if isinstance(row, dict) else row[index]


def load_preference(conn, tenant_id: str, event_type: str, channel: str) -> RoutePreference:
    """Load event-specific preference, then wildcard, then conservative default."""
    default_preference(event_type, channel)
    row = conn.execute(
        """
        select event_type,channel,enabled,delivery_mode,digest_interval_minutes,
               timezone,quiet_start,quiet_end,critical_bypass
          from notification_route_preference
         where tenant_id=%s and channel=%s and event_type in (%s, '*')
         order by case when event_type=%s then 0 else 1 end
         limit 1
        """, (tenant_id, channel, event_type, event_type),
    ).fetchone()
    if row is None:
        return default_preference(event_type, channel)
    preference = RoutePreference(
        event_type=event_type, channel=str(_cell(row, "channel", 1)),
        enabled=bool(_cell(row, "enabled", 2)), delivery_mode=str(_cell(row, "delivery_mode", 3)),
        digest_interval_minutes=_cell(row, "digest_interval_minutes", 4),
        timezone=str(_cell(row, "timezone", 5)), quiet_start=_cell(row, "quiet_start", 6),
        quiet_end=_cell(row, "quiet_end", 7), critical_bypass=bool(_cell(row, "critical_bypass", 8)),
    )
    _validate(preference)
    return preference


def _quiet_end(preference: RoutePreference, occurred_at: dt.datetime, zone: ZoneInfo) -> dt.datetime | None:
    if preference.quiet_start is None or preference.quiet_end is None:
        return None
    local = occurred_at.astimezone(zone)
    current = local.timetz().replace(tzinfo=None)
    start, end = preference.quiet_start, preference.quiet_end
    if start < end:
        if not start <= current < end:
            return None
        end_date = local.date()
    else:
        if current >= start:
            end_date = local.date() + dt.timedelta(days=1)
        elif current < end:
            end_date = local.date()
        else:
            return None
    return dt.datetime.combine(end_date, end, tzinfo=zone).astimezone(dt.timezone.utc)


def evaluate_delivery_policy(
    preference: RoutePreference, occurred_at: dt.datetime, severity: str, *,
    has_consent: bool = False, provider_configured: bool = False,
) -> PolicyDecision:
    """Return an eligibility decision only; this function never delivers."""
    zone = _validate(preference)
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")
    if severity not in ALLOWED_SEVERITIES:
        raise ValueError("unsupported notification severity")
    if preference.channel == "in_app":
        return PolicyDecision(IMMEDIATE)
    if not preference.enabled:
        return PolicyDecision(BLOCKED_DISABLED)
    if not has_consent:
        return PolicyDecision(BLOCKED_CONSENT)
    if not provider_configured:
        return PolicyDecision(BLOCKED_CONFIGURATION)
    quiet_end = _quiet_end(preference, occurred_at, zone)
    if quiet_end is not None and not (severity == "critical" and preference.critical_bypass):
        return PolicyDecision(DEFERRED_QUIET_HOURS, quiet_end)
    if preference.delivery_mode == "digest":
        return PolicyDecision(QUEUED_DIGEST)
    return PolicyDecision(ELIGIBLE)
