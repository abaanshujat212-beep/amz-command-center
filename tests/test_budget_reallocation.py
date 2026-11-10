from decimal import Decimal

import pytest

from services.rules.budget_reallocation import BudgetCandidate, propose_budget_reallocation


def campaign(campaign_id, budget, minimum, maximum, efficiency):
    return BudgetCandidate(campaign_id, *(Decimal(value) for value in (budget, minimum, maximum, efficiency)))


def test_allocation_conserves_budget_and_respects_bounds_with_explanations():
    result = propose_budget_reallocation(
        portfolio_id="p1",
        candidates=[campaign("donor", "20", "10", "30", "0.5"),
                    campaign("receiver", "15", "10", "25", "2")],
        target_efficiency=Decimal("1"), max_transfer=Decimal("8"), as_of="2026-11-10",
    )
    assert result.total_before == result.total_after == Decimal("35.00")
    assert [(item.campaign_id, item.after) for item in result.allocations] == [
        ("donor", Decimal("12.00")), ("receiver", Decimal("23.00")),
    ]
    assert result.approval_required is True
    assert result.transfers[0].explanation
    assert all(item.after >= 10 and item.after <= (12 if item.campaign_id == "donor" else 25)
               for item in result.allocations)


def test_no_eligible_pair_is_no_change_and_no_approval():
    result = propose_budget_reallocation(
        portfolio_id="p1", candidates=[campaign("at-target", "10", "5", "20", "1")],
        target_efficiency=Decimal("1"), max_transfer=Decimal("4"), as_of="today",
    )
    assert result.status == "no_change"
    assert result.transfers == ()
    assert result.approval_required is False


def test_ties_are_deterministic_and_idempotency_key_is_stable():
    candidates = [campaign("z-donor", "10", "0", "20", "0.5"),
                  campaign("a-donor", "10", "0", "20", "0.5"),
                  campaign("z-receiver", "10", "0", "20", "2"),
                  campaign("a-receiver", "10", "0", "20", "2")]
    kwargs = dict(portfolio_id="p", candidates=candidates, target_efficiency=Decimal("1"),
                  max_transfer=Decimal("2"), as_of="2026-11-10")
    first = propose_budget_reallocation(**kwargs)
    second = propose_budget_reallocation(**kwargs)
    assert first.transfers[0].donor_campaign_id == "a-donor"
    assert first.transfers[0].receiver_campaign_id == "a-receiver"
    assert first.idempotency_key == second.idempotency_key


def test_rejects_duplicate_ids_and_invalid_campaign_bounds():
    base = campaign("x", "10", "5", "20", "1")
    with pytest.raises(ValueError, match="unique"):
        propose_budget_reallocation(
            portfolio_id="p", candidates=[base, base], target_efficiency=Decimal("1"),
            max_transfer=Decimal("2"), as_of="today",
        )
    with pytest.raises(ValueError, match="within its bounds"):
        propose_budget_reallocation(
            portfolio_id="p", candidates=[campaign("x", "10", "11", "20", "1")],
            target_efficiency=Decimal("1"), max_transfer=Decimal("2"), as_of="today",
        )
