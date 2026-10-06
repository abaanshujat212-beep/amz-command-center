import datetime as dt
import uuid
from decimal import Decimal

import pytest

from services.config.goal_resolver import resolve_effective_goal


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    def execute(self, _query, params):
        self.params = params
        return FakeResult(self.rows)


def row(scope, scope_id, **values):
    return {
        "id": uuid.uuid4(),
        "scope_type": scope,
        "scope_id": scope_id,
        "target_acos": None,
        "min_acos": None,
        "max_acos": None,
        "target_roas": None,
        "acos_ceiling": None,
        "profit_floor": None,
        **values,
    }


def test_most_specific_non_null_value_wins_with_source_trace():
    conn = FakeConnection(
        [
            row("account", "a", target_acos=Decimal("0.30"), profit_floor=Decimal("0.10")),
            row("campaign", "c", target_acos=Decimal("0.20")),
            row("keyword", "k", max_acos=Decimal("0.25")),
        ]
    )
    result = resolve_effective_goal(
        conn,
        tenant_id="tenant",
        scopes={"account": "a", "campaign": "c", "keyword": "k"},
        as_of=dt.date(2026, 10, 6),
    )
    assert result.values["target_acos"] == Decimal("0.20")
    assert result.sources["target_acos"].scope_type == "campaign"
    assert result.values["max_acos"] == Decimal("0.25")
    assert result.sources["max_acos"].scope_type == "keyword"
    assert result.values["profit_floor"] == Decimal("0.10")
    assert result.sources["profit_floor"].scope_type == "account"
    assert conn.params[-2:] == (dt.date(2026, 10, 6), dt.date(2026, 10, 6))


def test_mismatched_pair_from_batched_query_is_ignored():
    conn = FakeConnection([row("campaign", "wrong", target_acos=Decimal("0.01"))])
    result = resolve_effective_goal(
        conn, tenant_id="tenant", scopes={"account": "a", "campaign": "c"}
    )
    assert result.values["target_acos"] is None
    assert result.sources["target_acos"] is None


@pytest.mark.parametrize(
    ("winner", "context"),
    [
        ("account", {"account": "account"}),
        ("portfolio", {"account": "account", "portfolio": "portfolio"}),
        (
            "product_family",
            {"account": "account", "portfolio": "portfolio", "product_family": "family"},
        ),
        ("asin", {"account": "account", "asin": "asin"}),
        ("campaign", {"account": "account", "campaign": "campaign"}),
        ("ad_group", {"account": "account", "campaign": "campaign", "ad_group": "group"}),
        ("target", {"account": "account", "ad_group": "group", "target": "target"}),
        ("keyword", {"account": "account", "ad_group": "group", "keyword": "keyword"}),
    ],
)
def test_every_hierarchy_level_can_be_the_most_specific_source(winner, context):
    rows = [
        row(scope, scope_id, target_acos=Decimal(index) / 100)
        for index, (scope, scope_id) in enumerate(context.items(), start=1)
    ]
    result = resolve_effective_goal(
        FakeConnection(rows), tenant_id="tenant", scopes=context, as_of=dt.date(2026, 10, 6)
    )
    assert result.sources["target_acos"].scope_type == winner


@pytest.mark.parametrize(
    "scopes,message",
    [
        ({"campaign": "c"}, "account scope is required"),
        ({"account": ""}, "account scope is required"),
        ({"account": "a", "campaign": " "}, "scope ids cannot be blank"),
        ({"account": "a", "unknown": "x"}, "unsupported PPC goal scope"),
    ],
)
def test_invalid_context_fails_predictably(scopes, message):
    with pytest.raises(ValueError, match=message):
        resolve_effective_goal(FakeConnection([]), tenant_id="tenant", scopes=scopes)
