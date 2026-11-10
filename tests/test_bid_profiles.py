import pytest

from services.rules.bid_profiles import (
    DEFAULT_PROFILE,
    PROFILE_VERSION,
    BidProfileError,
    resolve_bid_profile,
)


@pytest.mark.parametrize(
    ("name", "change", "clicks", "impressions", "cooldown"),
    [
        ("VERY_CONSERVATIVE", 0.05, 40, 200, 14),
        ("CONSERVATIVE", 0.10, 30, 150, 7),
        ("BALANCED", 0.15, 20, 100, 5),
        ("AGGRESSIVE", 0.20, 15, 75, 3),
        ("VERY_AGGRESSIVE", 0.25, 10, 50, 2),
    ],
)
def test_presets_are_inspectable_and_versioned(name, change, clicks, impressions, cooldown):
    profile = resolve_bid_profile({"bid_optimization_profile": name})
    assert profile.profile == name
    assert profile.profile_version == PROFILE_VERSION
    assert profile.max_change_pct == change
    assert profile.min_clicks == clicks
    assert profile.min_impressions == impressions
    assert profile.cooldown_days == cooldown
    assert profile.as_dict()["profile_version"] == PROFILE_VERSION


def test_existing_settings_default_to_very_conservative():
    profile = resolve_bid_profile({"unrelated_strategy_setting": True})
    assert profile.profile == DEFAULT_PROFILE
    assert profile.max_change_pct == 0.05


def test_custom_profile_validates_values_and_global_ceilings():
    values = {
        "max_change_pct": 0.12,
        "min_clicks": 50,
        "min_impressions": 250,
        "max_data_age_days": 4,
        "cooldown_days": 12,
    }
    profile = resolve_bid_profile(
        {
            "bid_optimization_profile": "CUSTOM",
            "bid_optimization_custom": values,
        }
    )
    assert profile.profile == "CUSTOM"
    assert profile.cooldown_days == 12

    for invalid in (
        {**values, "max_change_pct": 0.31},
        {**values, "min_clicks": 4},
        {**values, "min_impressions": 24},
        {**values, "max_data_age_days": 8},
        {**values, "cooldown_days": 91},
        {**values, "cooldown_days": True},
    ):
        with pytest.raises(BidProfileError):
            resolve_bid_profile(
                {
                    "bid_optimization_profile": "CUSTOM",
                    "bid_optimization_custom": invalid,
                }
            )


def test_tenant_guardrails_only_tighten_resolved_profile():
    profile = resolve_bid_profile({"bid_optimization_profile": "AGGRESSIVE"})
    policy = profile.calculation_policy(
        min_bid=0.1,
        max_bid=3.0,
        tenant_max_change_pct=0.08,
        tenant_min_clicks=100,
        tenant_min_impressions=500,
        tenant_max_data_age_days=1,
    )
    assert policy.max_change_pct == 0.08
    assert policy.min_clicks == 100
    assert policy.min_impressions == 500
    assert policy.max_data_age_days == 1

    relaxed = profile.calculation_policy(
        min_bid=0.1,
        max_bid=3.0,
        tenant_max_change_pct=0.9,
        tenant_min_clicks=1,
        tenant_min_impressions=1,
        tenant_max_data_age_days=99,
    )
    assert relaxed.max_change_pct == profile.max_change_pct
    assert relaxed.min_clicks == profile.min_clicks
    assert relaxed.min_impressions == profile.min_impressions
    assert relaxed.max_data_age_days == profile.max_data_age_days


@pytest.mark.parametrize(
    "settings",
    [
        {"bid_optimization_profile": "unknown"},
        {"bid_optimization_profile": "CUSTOM"},
        {
            "bid_optimization_profile": "CUSTOM",
            "bid_optimization_custom": {"max_change_pct": 0.1},
        },
        {"bid_optimization_profile": 42},
    ],
)
def test_invalid_or_incomplete_profile_fails_closed(settings):
    with pytest.raises(BidProfileError):
        resolve_bid_profile(settings)


def test_unsupported_profile_version_fails_closed():
    with pytest.raises(BidProfileError, match="unsupported"):
        resolve_bid_profile({}, version=2)
