import datetime as dt

import pytest

from services.notifications.policy import (
    BLOCKED_CONFIGURATION,
    BLOCKED_CONSENT,
    BLOCKED_DISABLED,
    DEFERRED_QUIET_HOURS,
    ELIGIBLE,
    IMMEDIATE,
    QUEUED_DIGEST,
    RoutePreference,
    default_preference,
    evaluate_delivery_policy,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def external(**overrides):
    values = {
        "event_type": "pipeline_failed",
        "channel": "email",
        "enabled": True,
    }
    values.update(overrides)
    return RoutePreference(**values)


def test_missing_preferences_are_conservative():
    assert default_preference("pipeline_failed", "in_app").enabled is True
    assert default_preference("pipeline_failed", "email").enabled is False
    assert evaluate_delivery_policy(
        default_preference("pipeline_failed", "in_app"), NOW, "warning"
    ).status == IMMEDIATE
    assert evaluate_delivery_policy(
        default_preference("pipeline_failed", "email"), NOW, "warning",
        has_consent=True, provider_configured=True,
    ).status == BLOCKED_DISABLED


def test_external_eligibility_requires_consent_and_configuration():
    preference = external()
    assert evaluate_delivery_policy(preference, NOW, "warning").status == BLOCKED_CONSENT
    assert evaluate_delivery_policy(
        preference, NOW, "warning", has_consent=True
    ).status == BLOCKED_CONFIGURATION
    assert evaluate_delivery_policy(
        preference, NOW, "warning", has_consent=True, provider_configured=True
    ).status == ELIGIBLE


def test_same_day_and_overnight_quiet_hours_are_deterministic():
    same_day = external(
        timezone="UTC", quiet_start=dt.time(9), quiet_end=dt.time(17)
    )
    decision = evaluate_delivery_policy(
        same_day, NOW, "warning", has_consent=True, provider_configured=True
    )
    assert decision.status == DEFERRED_QUIET_HOURS
    assert decision.eligible_at == dt.datetime(2026, 9, 16, 17, 0, tzinfo=UTC)

    overnight = external(
        timezone="Asia/Karachi", quiet_start=dt.time(22), quiet_end=dt.time(7)
    )
    at_midnight_local = dt.datetime(2026, 9, 15, 20, 0, tzinfo=UTC)
    decision = evaluate_delivery_policy(
        overnight, at_midnight_local, "warning",
        has_consent=True, provider_configured=True,
    )
    assert decision.status == DEFERRED_QUIET_HOURS
    assert decision.eligible_at == dt.datetime(2026, 9, 16, 2, 0, tzinfo=UTC)


def test_critical_bypass_does_not_bypass_consent_or_configuration():
    preference = external(
        quiet_start=dt.time(9), quiet_end=dt.time(17), critical_bypass=True
    )
    assert evaluate_delivery_policy(preference, NOW, "critical").status == BLOCKED_CONSENT
    assert evaluate_delivery_policy(
        preference, NOW, "critical", has_consent=True
    ).status == BLOCKED_CONFIGURATION
    assert evaluate_delivery_policy(
        preference, NOW, "critical", has_consent=True, provider_configured=True
    ).status == ELIGIBLE


def test_digest_is_a_queue_decision_not_delivery():
    preference = external(delivery_mode="digest", digest_interval_minutes=1440)
    assert evaluate_delivery_policy(
        preference, NOW, "info", has_consent=True, provider_configured=True
    ).status == QUEUED_DIGEST


@pytest.mark.parametrize(
    "preference",
    [
        RoutePreference("made_up", "email", True),
        RoutePreference("pipeline_failed", "fax", True),
        RoutePreference("pipeline_failed", "email", True, timezone="Mars/Olympus"),
        RoutePreference("pipeline_failed", "email", True, quiet_start=dt.time(9)),
        RoutePreference(
            "pipeline_failed", "email", True,
            delivery_mode="digest", digest_interval_minutes=15,
        ),
        RoutePreference("pipeline_failed", "in_app", False),
    ],
)
def test_invalid_preferences_fail_closed(preference):
    with pytest.raises(ValueError):
        evaluate_delivery_policy(preference, NOW, "warning")


def test_naive_timestamps_and_unknown_severity_fail_closed():
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_delivery_policy(external(), dt.datetime(2026, 9, 16), "warning")
    with pytest.raises(ValueError, match="severity"):
        evaluate_delivery_policy(external(), NOW, "healthy")
