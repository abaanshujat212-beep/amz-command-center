"""Schedule report jobs and route completed artifacts through notifications."""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.types.json import Jsonb

from services.notifications.router import InternalEvent, publish_in_app
from services.reports.jobs import enqueue_job

CHANNELS = frozenset({"in_app", "email", "whatsapp", "sms"})
CADENCES = frozenset({"daily", "weekly", "monthly"})
MANAGER_ROLES = frozenset({"owner", "admin"})


@dataclass(frozen=True)
class ScheduleSpec:
    cadence: str
    run_time: dt.time
    timezone: str
    weekday: int | None = None
    month_day: int | None = None


@dataclass(frozen=True)
class ScheduleRef:
    id: str
    next_run_at: dt.datetime


def create_schedule(
    conn,
    *,
    tenant_id: str,
    actor_user_id: str,
    actor_role: str,
    definition_code: str,
    definition_version: int,
    name: str,
    spec: ScheduleSpec,
    recipient_user_id: str,
    channels: list[str],
    output_format: str,
    date_window_days: int = 30,
    filters: dict | None = None,
    now: dt.datetime | None = None,
) -> ScheduleRef:
    """Create a schedule only for a tenant manager and active tenant recipient."""
    if actor_role not in MANAGER_ROLES:
        raise PermissionError("only tenant owners or admins may schedule reports")
    if not name.strip() or len(name) > 200:
        raise ValueError("schedule name is required and must be at most 200 characters")
    if not channels or len(channels) != len(set(channels)) or not set(channels) <= CHANNELS:
        raise ValueError("channels must be a unique non-empty supported channel list")
    if output_format not in {"csv", "xlsx", "pdf"}:
        raise ValueError("unsupported report format")
    if not 1 <= date_window_days <= 366:
        raise ValueError("date_window_days must be between 1 and 366")
    now = now or dt.datetime.now(dt.timezone.utc)
    due = next_run(spec, now)
    definition = conn.execute(
        """select id from report_definition
            where tenant_id=%s and code=%s and version=%s and active""",
        (tenant_id, definition_code, definition_version),
    ).fetchone()
    if definition is None:
        raise LookupError("active report definition not found for tenant")
    member = conn.execute(
        "select 1 from tenant_member where tenant_id=%s and user_id=%s",
        (tenant_id, recipient_user_id),
    ).fetchone()
    if member is None:
        raise ValueError("recipient must be an active tenant member")
    definition_id = definition["id"] if isinstance(definition, dict) else definition[0]
    row = conn.execute(
        """insert into report_delivery_schedule(
               tenant_id,report_definition_id,name,cadence,run_time,weekday,month_day,
               timezone,recipient_user_id,channels,date_window_days,output_format,
               filters,next_run_at,created_by)
           values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           returning id,next_run_at""",
        (
            tenant_id,
            definition_id,
            name.strip(),
            spec.cadence,
            spec.run_time,
            spec.weekday,
            spec.month_day,
            spec.timezone,
            recipient_user_id,
            channels,
            date_window_days,
            output_format,
            Jsonb(filters or {}),
            due,
            actor_user_id,
        ),
    ).fetchone()
    return ScheduleRef(str(row["id"]), row["next_run_at"])


def next_run(spec: ScheduleSpec, after: dt.datetime) -> dt.datetime:
    """Return the first scheduled UTC instant strictly after ``after``."""
    if after.tzinfo is None or after.utcoffset() is None:
        raise ValueError("after must be timezone-aware")
    if spec.cadence not in CADENCES:
        raise ValueError("unsupported report cadence")
    try:
        zone = ZoneInfo(spec.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid report schedule timezone") from exc
    local = after.astimezone(zone)
    if spec.cadence == "daily":
        candidate = dt.datetime.combine(local.date(), spec.run_time, zone)
        if candidate <= local:
            candidate += dt.timedelta(days=1)
    elif spec.cadence == "weekly":
        if spec.weekday is None or not 0 <= spec.weekday <= 6:
            raise ValueError("weekly schedules require weekday 0..6")
        days = (spec.weekday - local.weekday()) % 7
        candidate = dt.datetime.combine(local.date() + dt.timedelta(days=days), spec.run_time, zone)
        if candidate <= local:
            candidate += dt.timedelta(days=7)
    else:
        if spec.month_day is None or not 1 <= spec.month_day <= 28:
            raise ValueError("monthly schedules require month_day 1..28")
        year, month = local.year, local.month
        candidate = dt.datetime(
            year,
            month,
            spec.month_day,
            spec.run_time.hour,
            spec.run_time.minute,
            spec.run_time.second,
            tzinfo=zone,
        )
        if candidate <= local:
            month += 1
            if month == 13:
                year, month = year + 1, 1
            day = min(spec.month_day, calendar.monthrange(year, month)[1])
            candidate = dt.datetime(
                year,
                month,
                day,
                spec.run_time.hour,
                spec.run_time.minute,
                spec.run_time.second,
                tzinfo=zone,
            )
    return candidate.astimezone(dt.timezone.utc)


def enqueue_due(conn, *, tenant_id: str, now: dt.datetime, limit: int = 25) -> int:
    """Create idempotent report jobs for due schedules; removed users fail closed."""
    rows = conn.execute(
        """select s.*,d.code,d.version from report_delivery_schedule s
             join report_definition d on d.id=s.report_definition_id and d.tenant_id=s.tenant_id
            where s.tenant_id=%s and s.enabled and s.next_run_at<=%s and d.active
            order by s.next_run_at for update of s skip locked limit %s""",
        (tenant_id, now, limit),
    ).fetchall()
    created = 0
    for row in rows:
        scheduled_for = row["next_run_at"]
        member = conn.execute(
            "select 1 from tenant_member where tenant_id=%s and user_id=%s",
            (tenant_id, row["recipient_user_id"]),
        ).fetchone()
        spec = ScheduleSpec(
            row["cadence"], row["run_time"], row["timezone"], row["weekday"], row["month_day"]
        )
        following = next_run(spec, scheduled_for)
        if member is None:
            conn.execute(
                """insert into report_delivery_run(tenant_id,schedule_id,scheduled_for,status,reason)
                   values(%s,%s,%s,'blocked_recipient','recipient is not an active tenant member')
                   on conflict(tenant_id,schedule_id,scheduled_for) do nothing""",
                (tenant_id, row["id"], scheduled_for),
            )
        else:
            date_to = scheduled_for.date() - dt.timedelta(days=1)
            job = enqueue_job(
                conn,
                tenant_id=tenant_id,
                definition_code=row["code"],
                definition_version=int(row["version"]),
                requested_by=str(row["recipient_user_id"]),
                idempotency_key=f"schedule:{row['id']}:{scheduled_for.isoformat()}",
                date_from=date_to - dt.timedelta(days=int(row["date_window_days"]) - 1),
                date_to=date_to,
                filters=row["filters"],
                output_format=row["output_format"],
            )
            conn.execute(
                """insert into report_delivery_run(
                       tenant_id,schedule_id,report_job_id,scheduled_for,status)
                   values(%s,%s,%s,%s,'artifact_pending')
                   on conflict(tenant_id,schedule_id,scheduled_for) do nothing""",
                (tenant_id, row["id"], job.id, scheduled_for),
            )
            created += int(job.created)
        conn.execute(
            "update report_delivery_schedule set next_run_at=%s,updated_at=now() where tenant_id=%s and id=%s",
            (following, tenant_id, row["id"]),
        )
    return created


def route_completed(conn, *, tenant_id: str, run_id: str, now: dt.datetime) -> bool:
    """Revalidate recipient and artifact expiry, then use the canonical router."""
    row = conn.execute(
        """select r.id,r.report_job_id,s.name,s.recipient_user_id,s.channels,
                  a.id as artifact_id,a.expires_at
             from report_delivery_run r
             join report_delivery_schedule s on s.id=r.schedule_id and s.tenant_id=r.tenant_id
             join report_artifact a on a.report_job_id=r.report_job_id and a.tenant_id=r.tenant_id
             join report_job j on j.id=r.report_job_id and j.tenant_id=r.tenant_id
            where r.tenant_id=%s and r.id=%s and r.status='artifact_pending'
              and j.status='succeeded' for update of r""",
        (tenant_id, run_id),
    ).fetchone()
    if row is None:
        return False
    member = conn.execute(
        "select 1 from tenant_member where tenant_id=%s and user_id=%s",
        (tenant_id, row["recipient_user_id"]),
    ).fetchone()
    if member is None or row["expires_at"] <= now:
        state = "blocked_recipient" if member is None else "blocked_expired"
        reason = (
            "recipient is not an active tenant member" if member is None else "artifact expired"
        )
        conn.execute(
            "update report_delivery_run set status=%s,reason=%s,updated_at=now() where tenant_id=%s and id=%s",
            (state, reason, tenant_id, run_id),
        )
        return False
    published = publish_in_app(
        conn,
        InternalEvent(
            tenant_id=tenant_id,
            event_type="report_ready",
            source="report_worker",
            source_ref=str(row["artifact_id"]),
            dedupe_key=f"report-ready:{run_id}",
            severity="info",
            title=f"Scheduled report ready: {row['name']}",
            payload={
                "report_job_id": str(row["report_job_id"]),
                "artifact_id": str(row["artifact_id"]),
                "channels": list(row["channels"]),
            },
            occurred_at=now,
            recipient_ref=str(row["recipient_user_id"]),
        ),
    )
    conn.execute(
        """update notification_delivery set policy_decision='BLOCKED_DISABLED',updated_at=now()
             where tenant_id=%s and event_id=%s and not (channel = any(%s))""",
        (tenant_id, published.event_id, list(row["channels"])),
    )
    conn.execute(
        """update report_delivery_run
              set status='routed',notification_event_id=%s,updated_at=now()
            where tenant_id=%s and id=%s""",
        (published.event_id, tenant_id, run_id),
    )
    return True
