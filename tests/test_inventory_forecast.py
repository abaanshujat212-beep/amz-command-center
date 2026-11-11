from datetime import date, timedelta

import pytest

from services.rules.inventory_forecast import (
    DailyDemand,
    ExpectedReceipt,
    InventoryForecastInput,
    InventoryPosition,
    forecast_inventory,
)

AS_OF = date(2026, 1, 1)


def fixture(*, available=100, demand=5, lead=4, history_days=30, demand_data=None, **overrides):
    values = dict(
        sku="SKU-1", as_of=AS_OF,
        demand=(demand_data if demand_data is not None else tuple(
            DailyDemand(AS_OF - timedelta(days=offset), demand)
            for offset in range(history_days, 0, -1)
        )),
        position=InventoryPosition(available), source="csv_import", observed_at=AS_OF,
        lead_time_days=lead, lead_time_samples=10, seasonal_indices={},
    )
    values.update(overrides)
    return InventoryForecastInput(**values)


def test_current_days_supply_ignores_inbound_and_expected_later_stock():
    result = forecast_inventory(fixture(
        available=10,
        position=InventoryPosition(available_now=10, inbound=100, expected_later=50),
    ))
    assert result.status == "ready"
    assert result.available_now == 10
    assert result.days_of_supply_now == 2
    assert result.assumptions["inbound"] == 100
    assert result.assumptions["expected_later"] == 50


def test_seasonality_and_expected_receipt_affect_future_projection_only():
    as_of = date(2026, 1, 1)
    next_day = as_of + timedelta(days=1)
    inputs = fixture(
        as_of=as_of, available=20, lead=2,
        seasonal_indices={1: 5, 2: 10},
        receipts=(ExpectedReceipt(next_day, 10),),
    )
    result = forecast_inventory(inputs)
    assert result.available_now == 20
    assert result.forecast[0][1] == 10
    assert result.forecast[0][2] == 20
    assert result.projected_available_at_lead_time == 15


def test_sparse_history_fails_closed_without_forecast():
    result = forecast_inventory(fixture(history_days=4))
    assert result.status == "blocked"
    assert result.confidence == 0
    assert "sparse_demand_history" in result.blockers
    assert result.days_of_supply_now is None


def test_stale_and_partial_sources_reduce_confidence_explicitly():
    result = forecast_inventory(fixture(
        observed_at=AS_OF - timedelta(days=9), stale_after_days=3, partial_source=True,
    ))
    assert result.status == "reduced_confidence"
    assert result.confidence == 0
    assert "inventory_source_stale" in result.blockers
    assert "inventory_source_partial" in result.blockers


def test_lead_time_stockout_and_overstock_are_projected():
    stockout = forecast_inventory(fixture(available=5, demand=5, lead=4))
    assert stockout.projected_stockout_day == AS_OF + timedelta(days=1)
    assert stockout.stockout_before_receipt is True
    excess = forecast_inventory(fixture(available=500, demand=5, lead=4))
    assert excess.projected_excess_at_lead_time > 0
    assert excess.reorder_quantity == 0


def test_observed_lead_time_distribution_uses_conservative_ninetieth_percentile():
    result = forecast_inventory(fixture(lead_time_observations=(2, 3, 4, 12)))
    assert result.assumptions["lead_time_days"] == 12
    assert result.assumptions["lead_time_method"] == "p90_observed"
    assert result.forecast[-1][0] == AS_OF + timedelta(days=12)


def test_receipt_at_stockout_date_is_not_flagged_as_stockout_before_receipt():
    receipt_day = AS_OF + timedelta(days=2)
    result = forecast_inventory(fixture(
        available=10.1, demand=5, lead=4,
        receipts=(ExpectedReceipt(receipt_day, 10),),
    ))
    assert result.projected_stockout_day is None


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_current_stock_fails_closed(value):
    result = forecast_inventory(fixture(position=InventoryPosition(value)))
    assert result.status == "blocked"
    assert "available_now_unknown_or_invalid" in result.blockers


def test_duplicate_history_dates_and_invalid_receipts_are_reported():
    duplicate = DailyDemand(AS_OF, 2)
    result = forecast_inventory(fixture(demand_data=(duplicate, duplicate)))
    assert result.status == "blocked"
    assert "duplicate_demand_dates" in result.blockers
    bad_receipt = forecast_inventory(fixture(
        receipts=(ExpectedReceipt(AS_OF - timedelta(days=1), 5),),
    ))
    assert bad_receipt.status == "blocked"
    assert "invalid_expected_receipt" in bad_receipt.blockers


@pytest.mark.parametrize("arrival_offset", [0, 5, 30])
def test_receipts_outside_lead_time_do_not_inflate_lead_time_stock(arrival_offset):
    result = forecast_inventory(fixture(
        available=10, demand=5, lead=4,
        receipts=(ExpectedReceipt(AS_OF + timedelta(days=arrival_offset), 100),),
    ))
    assert result.projected_available_at_lead_time == 0
    assert result.reorder_quantity == 20
    assert result.forecast[-1][2] == result.projected_available_at_lead_time


def test_receipt_on_lead_time_boundary_counts_in_projected_stock():
    result = forecast_inventory(fixture(
        available=10, demand=5, lead=4,
        receipts=(ExpectedReceipt(AS_OF + timedelta(days=4), 100),),
    ))
    assert result.projected_available_at_lead_time == 90
    assert result.forecast[-1][2] == 90
    assert result.reorder_quantity == 0


def test_zero_lead_time_preserves_current_stock_without_future_demand_or_receipts():
    result = forecast_inventory(fixture(
        available=10, demand=5, lead=0,
        receipts=(ExpectedReceipt(AS_OF + timedelta(days=1), 100),),
    ))
    assert result.projected_available_at_lead_time == 10
    assert result.projected_excess_at_lead_time == 10
    assert result.reorder_quantity == 0


@pytest.mark.parametrize(("field", "value", "blocker"), [
    ("stale_after_days", "3", "invalid_freshness_policy"),
    ("stale_after_days", None, "invalid_freshness_policy"),
    ("stale_after_days", True, "invalid_freshness_policy"),
    ("minimum_history_days", "14", "invalid_history_policy"),
    ("minimum_history_days", 0, "invalid_history_policy"),
    ("minimum_history_days", True, "invalid_history_policy"),
    ("lead_time_samples", "10", "lead_time_distribution_missing"),
    ("lead_time_samples", 0, "lead_time_distribution_missing"),
])
def test_invalid_policy_blocks_before_arithmetic(field, value, blocker):
    result = forecast_inventory(fixture(**{field: value}))
    assert result.status == "blocked"
    assert blocker in result.blockers
    assert result.confidence == 0
    assert result.reorder_quantity is None
    assert result.forecast == ()


def test_duplicate_demand_cannot_produce_reorder_even_with_enough_history():
    source = fixture()
    result = forecast_inventory(fixture(demand_data=(*source.demand, source.demand[0])))
    assert result.status == "blocked"
    assert "duplicate_demand_dates" in result.blockers
    assert result.reorder_quantity is None


def test_future_demand_is_explicitly_blocked_instead_of_silently_discarded():
    source = fixture()
    result = forecast_inventory(fixture(demand_data=(
        *source.demand, DailyDemand(AS_OF + timedelta(days=1), 100),
    )))
    assert result.status == "blocked"
    assert "demand_timestamp_in_future" in result.blockers
    assert result.reorder_quantity is None


@pytest.mark.parametrize(("field", "value"), [
    ("as_of", "2026-01-01"), ("observed_at", None),
])
def test_invalid_input_dates_return_blocked_result(field, value):
    result = forecast_inventory(fixture(**{field: value}))
    assert result.status == "blocked"
    assert "invalid_input_dates" in result.blockers
    assert result.reorder_quantity is None


def test_invalid_demand_date_does_not_reach_sort_or_comparison():
    source = fixture()
    result = forecast_inventory(fixture(demand_data=(*source.demand, DailyDemand(None, 5))))
    assert result.status == "blocked"
    assert "invalid_demand_dates" in result.blockers


def test_invalid_lead_distribution_does_not_fall_back_to_actionable_summary():
    result = forecast_inventory(fixture(lead_time_observations=(2, float("nan"))))
    assert result.status == "blocked"
    assert "invalid_lead_time_distribution" in result.blockers
    assert result.reorder_quantity is None


def test_future_inventory_observation_cannot_produce_reorder():
    result = forecast_inventory(fixture(observed_at=AS_OF + timedelta(days=1)))
    assert result.status == "blocked"
    assert "source_timestamp_in_future" in result.blockers
    assert result.confidence == 0
    assert result.reorder_quantity is None


def test_lead_time_horizon_is_bounded_before_projection():
    result = forecast_inventory(fixture(lead=3661))
    assert result.status == "blocked"
    assert "forecast_horizon_exceeded" in result.blockers
    assert result.forecast == ()


def test_projection_cannot_overflow_supported_calendar():
    source = fixture(as_of=date.max - timedelta(days=1), observed_at=date.max - timedelta(days=1))
    result = forecast_inventory(source)
    assert result.status == "blocked"
    assert "forecast_date_range_exceeded" in result.blockers


def test_invalid_expected_receipt_date_is_blocked():
    result = forecast_inventory(fixture(receipts=(ExpectedReceipt(None, 10),)))
    assert result.status == "blocked"
    assert "invalid_expected_receipt" in result.blockers


def test_invalid_seasonality_cannot_produce_reorder_from_partial_profile():
    result = forecast_inventory(fixture(seasonal_indices={1: 1, 2: float("inf")}))
    assert result.status == "blocked"
    assert "invalid_seasonality_profile" in result.blockers
    assert result.reorder_quantity is None


@pytest.mark.parametrize(("available", "demand", "blocker"), [
    (100, 1e308, "nonfinite_forecast_calculation"),
    (1e308, 1e-300, "nonfinite_forecast_calculation"),
    (1e9, 5, "forecast_date_range_exceeded"),
])
def test_extreme_finite_quantities_fail_closed_instead_of_overflowing(available, demand, blocker):
    result = forecast_inventory(fixture(available=available, demand=demand))
    assert result.status == "blocked"
    assert blocker in result.blockers
    assert result.reorder_quantity is None
    assert result.forecast == ()
