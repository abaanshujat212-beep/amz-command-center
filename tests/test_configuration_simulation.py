from decimal import Decimal

import pytest

from services.config.simulation import Candidate, canary_ids, simulate


def candidates():
    return [
        Candidate("b", Decimal("20"), Decimal("24")),
        Candidate("a", Decimal("10"), Decimal("11")),
        Candidate("protected", Decimal("50"), Decimal("0"), True),
    ]


def test_simulation_is_deterministic_and_excludes_protected_overrides():
    first = simulate({"max_bid": 3}, candidates(), exposure_limit=2)
    second = simulate({"max_bid": 3}, reversed(candidates()), exposure_limit=2)
    assert first == second
    assert first.affected_ids == ("a", "b") and first.protected_ids == ("protected",)
    assert first.estimated_spend == Decimal("30") and first.estimated_spend_delta == Decimal("5")


def test_aggregate_exposure_is_fail_closed():
    with pytest.raises(ValueError, match="exceeds limit"):
        simulate({}, candidates(), exposure_limit=1)


def test_canary_is_deterministic_bounded_and_never_includes_protected():
    result = simulate({}, candidates(), exposure_limit=2)
    assert canary_ids(result, Decimal("50")) == canary_ids(result, Decimal("50"))
    assert len(canary_ids(result, Decimal("50"))) == 1
    assert "protected" not in canary_ids(result, Decimal("100"))
