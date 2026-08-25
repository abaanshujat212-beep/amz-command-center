import datetime as dt
from decimal import Decimal

import pytest

from services.economics.cost_import import CostRow, parse_row


def test_parse_minimum_cost_row_defaults_optional_values():
    row = parse_row({"sku": "SKU1", "valid_from": "2026-08-01", "cogs": "4.25"}, line_no=2)
    assert row == CostRow(
        sku="SKU1",
        asin=None,
        valid_from=dt.date(2026, 8, 1),
        valid_to=None,
        cogs=Decimal("4.25"),
        freight_in=Decimal("0"),
        amazon_referral_pct=Decimal("0.15"),
        fba_fee=Decimal("0"),
        storage_est=Decimal("0"),
        vat_rate=Decimal("0.20"),
        currency="GBP",
        note=None,
    )


def test_parse_rejects_negative_cost():
    with pytest.raises(ValueError, match="cogs must be non-negative"):
        parse_row({"sku": "SKU1", "valid_from": "2026-08-01", "cogs": "-1"}, line_no=2)


def test_parse_rejects_invalid_window():
    with pytest.raises(ValueError, match="valid_to must be after valid_from"):
        parse_row(
            {"sku": "SKU1", "valid_from": "2026-08-01", "valid_to": "2026-08-01", "cogs": "1"},
            line_no=2,
        )
