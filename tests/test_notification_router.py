import datetime as dt

import pytest

from services.notifications.router import InternalEvent, publish_in_app


class NoDatabase:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("invalid events must fail before database access")


def event(**overrides):
    values = {
        "tenant_id": "tenant-1",
        "event_type": "pipeline_failed",
        "source": "scheduler",
        "source_ref": "sales_traffic_asin_daily",
        "dedupe_key": "pipeline:failure:2026-09-15",
        "severity": "critical",
        "title": "Sales pipeline failed",
        "payload": {"dataset": "sales_traffic_asin_daily"},
        "occurred_at": dt.datetime(2026, 9, 15, tzinfo=dt.timezone.utc),
    }
    values.update(overrides)
    return InternalEvent(**values)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event_type", "made_up", "event type"),
        ("source", "email_provider", "source"),
        ("severity", "healthy", "severity"),
        ("dedupe_key", "", "dedupe_key"),
        ("payload", ["not", "an", "object"], "payload"),
        ("occurred_at", dt.datetime(2026, 9, 15), "timezone-aware"),
    ],
)
def test_unknown_or_invalid_internal_events_fail_before_database(field, value, message):
    with pytest.raises(ValueError, match=message):
        publish_in_app(NoDatabase(), event(**{field: value}))


def test_external_channels_are_not_publishable_sources():
    for source in ("email", "whatsapp", "sms"):
        with pytest.raises(ValueError, match="source"):
            publish_in_app(NoDatabase(), event(source=source))
