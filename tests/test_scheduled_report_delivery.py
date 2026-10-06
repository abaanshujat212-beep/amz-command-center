import datetime as dt

import pytest

from services.notifications.router import PublishResult
from services.reports import scheduled_delivery
from services.reports.scheduled_delivery import (
    ScheduleSpec,
    create_schedule,
    next_run,
    route_completed,
)

UTC = dt.timezone.utc


def test_daily_schedule_is_strictly_after_reference():
    spec = ScheduleSpec("daily", dt.time(9), "Europe/London")
    assert next_run(spec, dt.datetime(2026, 1, 5, 9, 0, tzinfo=UTC)) == dt.datetime(
        2026, 1, 6, 9, 0, tzinfo=UTC
    )


def test_weekly_and_monthly_schedule_are_deterministic():
    assert next_run(
        ScheduleSpec("weekly", dt.time(8), "UTC", weekday=0),
        dt.datetime(2026, 1, 6, tzinfo=UTC),
    ) == dt.datetime(2026, 1, 12, 8, tzinfo=UTC)
    assert next_run(
        ScheduleSpec("monthly", dt.time(7, 30), "UTC", month_day=15),
        dt.datetime(2026, 1, 16, tzinfo=UTC),
    ) == dt.datetime(2026, 2, 15, 7, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "spec",
    [
        ScheduleSpec("hourly", dt.time(9), "UTC"),
        ScheduleSpec("weekly", dt.time(9), "UTC"),
        ScheduleSpec("monthly", dt.time(9), "UTC", month_day=31),
        ScheduleSpec("daily", dt.time(9), "Mars/Olympus"),
    ],
)
def test_invalid_schedules_fail_closed(spec):
    with pytest.raises(ValueError):
        next_run(spec, dt.datetime(2026, 1, 1, tzinfo=UTC))


def test_only_owner_or_admin_can_create_schedules():
    with pytest.raises(PermissionError):
        create_schedule(
            object(),
            tenant_id="tenant-1",
            actor_user_id="user-1",
            actor_role="viewer",
            definition_code="account",
            definition_version=1,
            name="Daily",
            spec=ScheduleSpec("daily", dt.time(9), "UTC"),
            recipient_user_id="user-1",
            channels=["in_app"],
            output_format="pdf",
            now=dt.datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_duplicate_or_unknown_channels_fail_before_database_access():
    base = dict(
        conn=object(),
        tenant_id="tenant-1",
        actor_user_id="owner-1",
        actor_role="owner",
        definition_code="account",
        definition_version=1,
        name="Daily",
        spec=ScheduleSpec("daily", dt.time(9), "UTC"),
        recipient_user_id="owner-1",
        output_format="pdf",
        now=dt.datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="channels"):
        create_schedule(**base, channels=["email", "email"])
    with pytest.raises(ValueError, match="channels"):
        create_schedule(**base, channels=["fax"])


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class RouteConnection:
    def __init__(self, route_row, member=(1,)):
        self.route_row = route_row
        self.member = member
        self.statements = []

    def execute(self, sql, parameters):
        self.statements.append((" ".join(sql.split()), parameters))
        if "from report_delivery_run r" in sql:
            return Result(self.route_row)
        if "from tenant_member" in sql:
            return Result(self.member)
        return Result()


def completed_row(**overrides):
    values = {
        "id": "run-1",
        "report_job_id": "job-1",
        "name": "Daily performance",
        "recipient_user_id": "user-1",
        "channels": ["in_app", "email"],
        "artifact_id": "artifact-1",
        "expires_at": dt.datetime(2026, 1, 2, tzinfo=UTC),
    }
    values.update(overrides)
    return values


def test_expired_artifact_is_blocked_before_notification(monkeypatch):
    conn = RouteConnection(completed_row(expires_at=dt.datetime(2026, 1, 1, tzinfo=UTC)))

    def unexpected_publish(*_args, **_kwargs):
        raise AssertionError("expired artifacts must not enter the notification router")

    monkeypatch.setattr(scheduled_delivery, "publish_in_app", unexpected_publish)
    assert (
        route_completed(
            conn,
            tenant_id="tenant-1",
            run_id="run-1",
            now=dt.datetime(2026, 1, 1, 1, tzinfo=UTC),
        )
        is False
    )
    assert any("status=%s,reason=%s" in sql for sql, _ in conn.statements)
    assert conn.statements[-1][1][0] == "blocked_expired"


def test_completed_artifact_reuses_router_and_links_audit_event(monkeypatch):
    conn = RouteConnection(completed_row())
    published = []

    def publish(_conn, event):
        published.append(event)
        return PublishResult("event-1", "alert-1", True)

    monkeypatch.setattr(scheduled_delivery, "publish_in_app", publish)
    assert (
        route_completed(
            conn,
            tenant_id="tenant-1",
            run_id="run-1",
            now=dt.datetime(2026, 1, 1, 1, tzinfo=UTC),
        )
        is True
    )
    assert published[0].event_type == "report_ready"
    assert published[0].recipient_ref == "user-1"
    assert published[0].dedupe_key == "report-ready:run-1"
    assert any("not (channel = any(%s))" in sql for sql, _ in conn.statements)
    audit_update = next(
        parameters for sql, parameters in conn.statements if "notification_event_id=%s" in sql
    )
    assert audit_update == ("event-1", "tenant-1", "run-1")
