import datetime as dt

import pytest

from services.reports.scheduled_delivery import ScheduleSpec
from services.research.opportunity_feed import create_schedule


class NoDatabase:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("invalid input must fail before database access")


def test_feed_schedule_is_manager_only_and_weekly_or_monthly():
    with pytest.raises(PermissionError):
        create_schedule(
            NoDatabase(),
            tenant_id="t",
            project_id="p",
            actor_user_id="u",
            actor_role="analyst",
            spec=ScheduleSpec("weekly", dt.time(9), "UTC", weekday=1),
        )
    with pytest.raises(ValueError, match="weekly or monthly"):
        create_schedule(
            NoDatabase(),
            tenant_id="t",
            project_id="p",
            actor_user_id="u",
            actor_role="owner",
            spec=ScheduleSpec("daily", dt.time(9), "UTC"),
        )


def test_digest_requires_recipient_before_database_access():
    with pytest.raises(ValueError, match="recipient"):
        create_schedule(
            NoDatabase(),
            tenant_id="t",
            project_id="p",
            actor_user_id="u",
            actor_role="owner",
            spec=ScheduleSpec("weekly", dt.time(9), "UTC", weekday=1),
            digest_enabled=True,
        )
