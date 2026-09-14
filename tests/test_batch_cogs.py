from decimal import Decimal

import pytest

from services.economics.batch_cogs import Receipt, Sale, calculate


def receipt(id, date, qty, cost, currency="GBP"):
    return Receipt(id, date, Decimal(qty), Decimal(cost), currency)


def sale(ref, date, qty, currency="GBP"):
    return Sale(ref, date, Decimal(qty), currency)


def test_fifo_partial_batches_golden_fixture():
    result = calculate("fifo", [receipt("b1", "2026-01-01", "5", "2"), receipt("b2", "2026-01-02", "5", "3")], [sale("s1", "2026-01-03", "7")])
    assert [(x.batch_id, x.quantity, x.allocated_cost) for x in result.allocations] == [
        ("b1", Decimal("5"), Decimal("10")), ("b2", Decimal("2"), Decimal("6"))
    ]
    assert result.complete


def test_weighted_average_is_deterministic():
    result = calculate("weighted_average", [receipt("b2", "2026-01-02", "5", "3"), receipt("b1", "2026-01-01", "5", "1")], [sale("s1", "2026-01-03", "4")])
    assert result.allocations[0].unit_cost == Decimal("2")
    assert result.allocations[0].allocated_cost == Decimal("8")


def test_by_period_uses_only_receipts_in_sale_month():
    result = calculate("by_period", [receipt("old", "2025-12-31", "10", "1"), receipt("new", "2026-01-02", "10", "4")], [sale("s1", "2026-01-05", "2")])
    assert result.allocations[0].unit_cost == Decimal("4")


def test_negative_stock_is_explicitly_incomplete():
    result = calculate("fifo", [receipt("b1", "2026-01-01", "2", "3")], [sale("s1", "2026-01-02", "3")])
    assert not result.complete
    assert result.incomplete_reason == "negative_stock"
    assert result.allocations[-1].allocated_cost is None


def test_return_reverses_at_last_known_fifo_cost():
    result = calculate("fifo", [receipt("b1", "2026-01-01", "2", "3")], [sale("s1", "2026-01-02", "1"), sale("r1", "2026-01-03", "-1")])
    assert result.allocations[-1].allocated_cost == Decimal("-3")


def test_currency_mismatch_fails_closed():
    with pytest.raises(ValueError, match="one currency"):
        calculate("fifo", [receipt("b1", "2026-01-01", "1", "1", "GBP")], [sale("s1", "2026-01-02", "1", "USD")])
