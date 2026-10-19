from decimal import Decimal

import pytest

from services.rules.scoring import ScoreComponent, calculate_score


def test_missing_component_lowers_coverage_but_does_not_become_zero():
    result = calculate_score([ScoreComponent("efficiency", Decimal("3"), Decimal("80"), "ok"), ScoreComponent("conversion", Decimal("1"), None, "missing")])
    assert result.score == Decimal("80.00")
    assert result.coverage == Decimal("75.00")
    assert result.components[1]["available"] is False


def test_all_missing_is_not_an_invented_zero():
    result = calculate_score([ScoreComponent("efficiency", Decimal("1"), None, "missing")])
    assert result.score is None
    assert result.coverage == Decimal("0.00")


@pytest.mark.parametrize("value", [Decimal("-1"), Decimal("101")])
def test_out_of_range_evidence_fails(value):
    with pytest.raises(ValueError):
        calculate_score([ScoreComponent("bad", Decimal("1"), value, "bad")])
