"""Deterministic, source-aware inventory demand and availability forecast."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping, Sequence

# Bound daily projections to ten years even when callers supply a malformed lead time.
MAX_FORECAST_DAYS = 3660


@dataclass(frozen=True)
class DailyDemand:
    day: date
    units: float


@dataclass(frozen=True)
class InventoryPosition:
    """Quantities for one SKU/location; only available_now counts as on hand."""

    available_now: float | None
    reserved: float | None = 0
    inbound: float | None = 0
    expected_later: float | None = 0


@dataclass(frozen=True)
class ExpectedReceipt:
    arrival_day: date
    quantity: float
    status: str = "expected"


@dataclass(frozen=True)
class InventoryForecastInput:
    sku: str
    as_of: date
    demand: Sequence[DailyDemand]
    position: InventoryPosition
    source: str
    observed_at: date
    lead_time_days: float | None
    lead_time_samples: int
    seasonal_indices: Mapping[int, float]
    lead_time_observations: Sequence[float] = ()
    receipts: Sequence[ExpectedReceipt] = ()
    stale_after_days: int = 3
    minimum_history_days: int = 14
    partial_source: bool = False


@dataclass(frozen=True)
class InventoryForecast:
    sku: str
    status: str
    confidence: float
    blockers: tuple[str, ...]
    assumptions: Mapping[str, Any]
    available_now: float | None
    average_daily_demand: float | None
    days_of_supply_now: float | None
    projected_stockout_day: date | None
    stockout_before_receipt: bool | None
    projected_available_at_lead_time: float | None
    projected_excess_at_lead_time: float | None
    reorder_quantity: float | None
    reorder_due_day: date | None
    forecast: tuple[tuple[date, float, float], ...]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["blockers"] = list(self.blockers)
        result["forecast"] = [
            {"day": day.isoformat(), "demand": demand, "projected_available": available}
            for day, demand, available in self.forecast
        ]
        return result


def _finite_nonnegative(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _empty(source: InventoryForecastInput, blockers: list[str]) -> InventoryForecast:
    return InventoryForecast(
        sku=source.sku, status="blocked", confidence=0.0, blockers=tuple(blockers),
        assumptions={"source": source.source, "observed_at": (
            source.observed_at.isoformat() if type(source.observed_at) is date else None
        )},
        available_now=None, average_daily_demand=None, days_of_supply_now=None,
        projected_stockout_day=None, stockout_before_receipt=None,
        projected_available_at_lead_time=None, projected_excess_at_lead_time=None,
        reorder_quantity=None, reorder_due_day=None, forecast=(),
    )


def forecast_inventory(inputs: InventoryForecastInput) -> InventoryForecast:
    """Calculate time-phased stock and demand without treating expected stock as current.

    Demand is the unweighted mean of supplied daily sales, adjusted by the ratio
    of the as-of seasonal index to each projection day's index. A zero index
    means no seasonal adjustment. Only confirmed or expected receipts whose
    status is explicitly ``expected`` enter future positions. Invalid inputs
    return a blocked result without replenishment quantities; daily projection
    horizons are limited to 3,660 days and Python's supported calendar range.
    """
    if not inputs.sku or not inputs.source:
        return _empty(inputs, ["missing_identity_or_source"])
    blockers: list[str] = []
    # Check policies and calendar types before comparisons, divisions or sorting.
    if type(inputs.stale_after_days) is not int or inputs.stale_after_days < 0:
        blockers.append("invalid_freshness_policy")
    if type(inputs.minimum_history_days) is not int or inputs.minimum_history_days < 1:
        blockers.append("invalid_history_policy")
    if type(inputs.lead_time_samples) is not int or inputs.lead_time_samples < 1:
        blockers.append("lead_time_distribution_missing")
    if type(inputs.as_of) is not date or type(inputs.observed_at) is not date:
        blockers.append("invalid_input_dates")
    if blockers:
        return _empty(inputs, blockers)
    if any(type(item.day) is not date for item in inputs.demand):
        return _empty(inputs, ["invalid_demand_dates"])
    available = _finite_nonnegative(inputs.position.available_now)
    if available is None:
        blockers.append("available_now_unknown_or_invalid")
    if inputs.observed_at > inputs.as_of:
        blockers.append("source_timestamp_in_future")
    age = (inputs.as_of - inputs.observed_at).days
    if age > inputs.stale_after_days:
        blockers.append("inventory_source_stale")
    if inputs.partial_source:
        blockers.append("inventory_source_partial")
    history = sorted(inputs.demand, key=lambda item: item.day)
    if len({item.day for item in history}) != len(history):
        blockers.append("duplicate_demand_dates")
    if any(item.day > inputs.as_of for item in history):
        blockers.append("demand_timestamp_in_future")
    valid_demand = [_finite_nonnegative(item.units) for item in history]
    if any(value is None for value in valid_demand):
        blockers.append("invalid_demand_history")
    values = [value for value in valid_demand if value is not None]
    if len(values) < inputs.minimum_history_days:
        blockers.append("sparse_demand_history")
    lead = _finite_nonnegative(inputs.lead_time_days)
    lead_distribution = [_finite_nonnegative(value) for value in inputs.lead_time_observations]
    if any(value is None for value in lead_distribution):
        blockers.append("invalid_lead_time_distribution")
        lead_distribution = []
    if lead_distribution:
        sorted_leads = sorted(value for value in lead_distribution if value is not None)
        lead = sorted_leads[math.ceil(0.9 * len(sorted_leads)) - 1]
    if lead is None:
        blockers.append("lead_time_unknown")
    if lead is not None and lead > MAX_FORECAST_DAYS:
        blockers.append("forecast_horizon_exceeded")
    indices: dict[int, float] = {}
    for day_of_year, index in inputs.seasonal_indices.items():
        valid_index = _finite_nonnegative(index)
        if type(day_of_year) is not int or not 1 <= day_of_year <= 366 or valid_index is None:
            blockers.append("invalid_seasonality_profile")
            break
        indices[day_of_year] = valid_index
    # Stale/partial sources retain an explicitly reduced-confidence readout.
    # Invalid inputs must not yield an actionable replenishment calculation.
    if any(blocker not in {"inventory_source_stale", "inventory_source_partial"}
           for blocker in blockers):
        return _empty(inputs, blockers)
    lead_days = math.ceil(lead)
    if inputs.as_of.toordinal() + max(lead_days, 1) > date.max.toordinal():
        return _empty(inputs, [*blockers, "forecast_date_range_exceeded"])

    average = sum(values) / len(values) if values else 0.0
    if not math.isfinite(average):
        return _empty(inputs, [*blockers, "nonfinite_forecast_calculation"])
    base_index = indices.get(inputs.as_of.timetuple().tm_yday, 0.0)
    receipts: dict[date, float] = {}
    invalid_receipt = False
    for receipt in inputs.receipts:
        if receipt.status != "expected":
            continue
        quantity = _finite_nonnegative(receipt.quantity)
        if (type(receipt.arrival_day) is not date
                or receipt.arrival_day < inputs.as_of or quantity is None):
            invalid_receipt = True
            break
        receipts[receipt.arrival_day] = receipts.get(receipt.arrival_day, 0.0) + quantity
    if invalid_receipt:
        blockers.append("invalid_expected_receipt")
        return _empty(inputs, blockers)

    horizon = max(lead_days, 1)
    projected = available
    stockout_day: date | None = None
    stockout_before_receipt: bool | None = None
    points: list[tuple[date, float, float]] = []
    for offset in range(1, horizon + 1):
        day = inputs.as_of.fromordinal(inputs.as_of.toordinal() + offset)
        index = indices.get(day.timetuple().tm_yday, base_index)
        seasonal_multiplier = index / base_index if base_index > 0 else 1.0
        day_demand = average * seasonal_multiplier
        projected += receipts.get(day, 0.0)
        projected -= day_demand
        if not math.isfinite(day_demand) or not math.isfinite(projected):
            return _empty(inputs, [*blockers, "nonfinite_forecast_calculation"])
        if projected <= 0 and day_demand > 0 and stockout_day is None:
            stockout_day = day
            stockout_before_receipt = not any(
                receipt.status == "expected" and receipt.arrival_day <= day
                and _finite_nonnegative(receipt.quantity) is not None
                for receipt in inputs.receipts
            )
        points.append((day, day_demand, max(0.0, projected)))

    days_supply = available / average if average > 0 else None
    if days_supply is not None and not math.isfinite(days_supply):
        return _empty(inputs, [*blockers, "nonfinite_forecast_calculation"])
    lead_demand = sum(point[1] for point in points[:lead_days])
    lead_day = inputs.as_of.fromordinal(inputs.as_of.toordinal() + lead_days)
    receipts_by_lead = sum(
        quantity for arrival, quantity in receipts.items()
        if inputs.as_of < arrival <= lead_day
    )
    if not math.isfinite(receipts_by_lead) or not math.isfinite(lead_demand):
        return _empty(inputs, [*blockers, "nonfinite_forecast_calculation"])
    available_at_lead = max(0.0, available + receipts_by_lead - lead_demand)
    # Replenish projected lead-time stock up to one lead-time of safety stock.
    safety_stock = average * lead
    if not math.isfinite(available_at_lead) or not math.isfinite(safety_stock):
        return _empty(inputs, [*blockers, "nonfinite_forecast_calculation"])
    reorder_quantity = max(0.0, safety_stock - available_at_lead)
    due_ordinal = inputs.as_of.toordinal() + max(0, math.floor((days_supply or 0.0) - lead))
    if due_ordinal > date.max.toordinal():
        return _empty(inputs, [*blockers, "forecast_date_range_exceeded"])
    due_day = date.fromordinal(due_ordinal)
    confidence = min(1.0, len(values) / max(inputs.minimum_history_days * 2, 1))
    confidence *= min(1.0, inputs.lead_time_samples / 10)
    confidence *= max(0.0, 1.0 - max(age, 0) / max(inputs.stale_after_days + 1, 1))
    if inputs.partial_source:
        confidence *= 0.5
    if "invalid_seasonality_profile" in blockers:
        confidence *= 0.5
    if base_index == 0 and indices:
        blockers.append("seasonality_base_missing")
    if lead_days == 0:
        projected = available
    return InventoryForecast(
        inputs.sku, "reduced_confidence" if blockers else "ready", round(confidence, 4),
        tuple(blockers),
        {"source": inputs.source, "observed_at": inputs.observed_at.isoformat(),
         "history_days": len(values), "lead_time_days": lead, "lead_time_samples": inputs.lead_time_samples,
         "lead_time_method": "p90_observed" if lead_distribution else "provided_summary",
         "seasonality_method": "daily_index_ratio", "receipts_affect_future_only": True,
         "reserved": inputs.position.reserved, "inbound": inputs.position.inbound,
         "expected_later": inputs.position.expected_later, "safety_stock_days": lead},
        available, round(average, 4), round(days_supply, 4) if days_supply is not None else None,
        stockout_day, stockout_before_receipt, round(available_at_lead, 4),
        round(max(0.0, available_at_lead - safety_stock), 4), round(reorder_quantity, 4),
        due_day, tuple(points),
    )
