"""Versioned, safety-bounded bid optimization profiles.

Profiles are intended to live in immutable ``strategy_version.settings`` JSON.
Existing strategies without a profile resolve to the conservative preset.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from services.rules.bid_optimizer import BidCalculationPolicy

PROFILE_VERSION = 1
DEFAULT_PROFILE = "VERY_CONSERVATIVE"

# Values are intentional defaults, not authorization to apply a recommendation.
_PRESETS: dict[str, dict[str, float | int]] = {
    "VERY_CONSERVATIVE": {
        "max_change_pct": 0.05,
        "min_clicks": 40,
        "min_impressions": 200,
        "max_data_age_days": 2,
        "cooldown_days": 14,
    },
    "CONSERVATIVE": {
        "max_change_pct": 0.10,
        "min_clicks": 30,
        "min_impressions": 150,
        "max_data_age_days": 3,
        "cooldown_days": 7,
    },
    "BALANCED": {
        "max_change_pct": 0.15,
        "min_clicks": 20,
        "min_impressions": 100,
        "max_data_age_days": 3,
        "cooldown_days": 5,
    },
    "AGGRESSIVE": {
        "max_change_pct": 0.20,
        "min_clicks": 15,
        "min_impressions": 75,
        "max_data_age_days": 2,
        "cooldown_days": 3,
    },
    "VERY_AGGRESSIVE": {
        "max_change_pct": 0.25,
        "min_clicks": 10,
        "min_impressions": 50,
        "max_data_age_days": 1,
        "cooldown_days": 2,
    },
}

# Keep profile settings inside platform caps. Tenant guardrails can only tighten them.
GLOBAL_MAX_CHANGE_PCT = 0.30
GLOBAL_MIN_CLICKS = 5
GLOBAL_MIN_IMPRESSIONS = 25
GLOBAL_MAX_DATA_AGE_DAYS = 7
GLOBAL_MAX_COOLDOWN_DAYS = 90
_FIELDS = frozenset(_PRESETS["BALANCED"])


class BidProfileError(ValueError):
    """Profile selection or custom values violate the safe configuration contract."""


@dataclass(frozen=True)
class ResolvedBidProfile:
    profile: str
    profile_version: int
    max_change_pct: float
    min_clicks: int
    min_impressions: int
    max_data_age_days: int
    cooldown_days: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def calculation_policy(
        self,
        *,
        min_bid: float,
        max_bid: float,
        tenant_max_change_pct: float | None = None,
        tenant_min_clicks: int | None = None,
        tenant_min_impressions: int | None = None,
        tenant_max_data_age_days: int | None = None,
    ) -> BidCalculationPolicy:
        """Apply tenant restrictions by tightening the profile's safe limits."""
        return BidCalculationPolicy(
            min_bid=min_bid,
            max_bid=max_bid,
            max_change_pct=min(
                self.max_change_pct,
                tenant_max_change_pct
                if tenant_max_change_pct is not None
                else GLOBAL_MAX_CHANGE_PCT,
                GLOBAL_MAX_CHANGE_PCT,
            ),
            min_clicks=max(
                self.min_clicks,
                tenant_min_clicks if tenant_min_clicks is not None else GLOBAL_MIN_CLICKS,
            ),
            min_impressions=max(
                self.min_impressions,
                tenant_min_impressions
                if tenant_min_impressions is not None
                else GLOBAL_MIN_IMPRESSIONS,
            ),
            max_data_age_days=min(
                self.max_data_age_days,
                tenant_max_data_age_days
                if tenant_max_data_age_days is not None
                else GLOBAL_MAX_DATA_AGE_DAYS,
            ),
        )


def resolve_bid_profile(
    settings: Mapping[str, Any] | None,
    *,
    version: int = PROFILE_VERSION,
) -> ResolvedBidProfile:
    """Resolve a strategy settings object; missing settings default conservatively."""
    if type(version) is not int or version != PROFILE_VERSION:
        raise BidProfileError(f"unsupported bid profile version: {version!r}")
    if settings is None:
        settings = {}
    if not isinstance(settings, Mapping):
        raise BidProfileError("bid profile settings must be an object")

    profile = settings.get("bid_optimization_profile", DEFAULT_PROFILE)
    if not isinstance(profile, str):
        raise BidProfileError("bid_optimization_profile must be a string")
    profile = profile.upper()
    if profile == "CUSTOM":
        custom = settings.get("bid_optimization_custom")
        if not isinstance(custom, Mapping):
            raise BidProfileError("CUSTOM profile requires bid_optimization_custom")
        unknown = set(custom) - _FIELDS
        missing = _FIELDS - set(custom)
        if unknown or missing:
            raise BidProfileError(
                f"custom profile fields invalid; missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        values: dict[str, float | int] = dict(custom)
    else:
        if profile not in _PRESETS:
            raise BidProfileError(f"unknown bid optimization profile: {profile}")
        values = dict(_PRESETS[profile])

    change = _number(values["max_change_pct"], "max_change_pct")
    if not 0 < change <= GLOBAL_MAX_CHANGE_PCT:
        raise BidProfileError(f"max_change_pct must be in (0, {GLOBAL_MAX_CHANGE_PCT}]")
    checks = (
        ("min_clicks", GLOBAL_MIN_CLICKS, 100_000),
        ("min_impressions", GLOBAL_MIN_IMPRESSIONS, 1_000_000),
        ("max_data_age_days", 0, GLOBAL_MAX_DATA_AGE_DAYS),
        ("cooldown_days", 0, GLOBAL_MAX_COOLDOWN_DAYS),
    )
    normalized: dict[str, int] = {}
    for name, lower, upper in checks:
        value = values[name]
        if type(value) is not int or not lower <= value <= upper:
            raise BidProfileError(f"{name} must be an integer in [{lower}, {upper}]")
        normalized[name] = value
    return ResolvedBidProfile(
        profile=profile,
        profile_version=PROFILE_VERSION,
        max_change_pct=change,
        min_clicks=normalized["min_clicks"],
        min_impressions=normalized["min_impressions"],
        max_data_age_days=normalized["max_data_age_days"],
        cooldown_days=normalized["cooldown_days"],
    )


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise BidProfileError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BidProfileError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise BidProfileError(f"{field} must be finite")
    return result
