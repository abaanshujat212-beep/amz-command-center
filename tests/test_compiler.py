"""Compiler tests. Rules are user data going into SQL, so this is a security test."""

import pytest

from services.rules.compiler import (
    RuleValidationError,
    compile_condition,
    render_reason,
    resolve_action,
    validate,
)
from services.rules.starter_rules import STARTER_RULES


# ------------------------------------------------------------- happy path
def test_simple_comparison_binds_parameters():
    sql, params = compile_condition({"<": [{"var": "acos"}, 0.35]})
    assert "m.acos" in sql
    assert params == [0.35], "literals must be bound, not interpolated"
    assert "0.35" not in sql


def test_metric_to_metric_comparison():
    sql, params = compile_condition(
        {"<": [{"var": "acos"}, {"var": "break_even_acos"}]}
    )
    assert "m.acos" in sql and "e.break_even_acos" in sql
    assert params == []


def test_nested_and_with_arithmetic():
    sql, params = compile_condition(
        {
            "and": [
                {"<": [{"var": "acos"}, {"*": [{"var": "break_even_acos"}, 0.8]}]},
                {">=": [{"var": "clicks"}, 15]},
            ]
        }
    )
    assert " and " in sql
    assert params == [0.8, 15]


def test_all_eight_starter_rules_compile():
    for rule in STARTER_RULES:
        validate(rule["condition"])          # must not raise


# --------------------------------------------------------------- injection
def test_sql_injection_in_metric_name_rejected():
    with pytest.raises(RuleValidationError, match="unknown metric"):
        compile_condition({"<": [{"var": "acos; drop table action; --"}, 1]})


def test_arbitrary_column_reference_rejected():
    with pytest.raises(RuleValidationError, match="unknown metric"):
        compile_condition({"==": [{"var": "amazon_connection.refresh_token_encrypted"}, 1]})


def test_unknown_operator_rejected():
    with pytest.raises(RuleValidationError, match="not allowed"):
        compile_condition({"exec": [{"var": "acos"}, 1]})


def test_string_literal_is_parameterised_not_inlined():
    sql, params = compile_condition({"==": [{"var": "is_already_negative"}, "'; delete from rule; --"]})
    assert "delete" not in sql.lower()
    assert params == ["'; delete from rule; --"]


def test_multiple_operators_in_one_object_rejected():
    with pytest.raises(RuleValidationError, match="exactly one operator"):
        compile_condition({"<": [{"var": "acos"}, 1], ">": [{"var": "cvr"}, 1]})


def test_depth_limit():
    node = {"var": "acos"}
    for _ in range(12):
        node = {"*": [node, 1]}
    with pytest.raises(RuleValidationError, match="nested deeper"):
        compile_condition({"<": [node, 1]})


def test_empty_condition_rejected():
    with pytest.raises(RuleValidationError):
        compile_condition({})


# ------------------------------------------------------------ null safety
def test_comparison_guards_against_nulls():
    """A keyword with no clicks has null ACOS. Null must never match."""
    sql, _ = compile_condition({"<": [{"var": "acos"}, 0.35]})
    assert "is not null" in sql


def test_division_guards_against_zero():
    sql, _ = compile_condition({"<": [{"/": [{"var": "cost"}, {"var": "clicks"}]}, 1]})
    assert "nullif" in sql


# --------------------------------------------------------------- actions
def test_multiply_action():
    assert resolve_action({"type": "set_bid", "op": "multiply", "factor": 1.10}, 1.00) == 1.10


def test_add_pct_action():
    assert resolve_action({"type": "set_budget", "op": "add_pct", "delta_pct": -20}, 20.0) == 16.0


def test_pause_action_has_no_value():
    assert resolve_action({"type": "pause"}, 1.00) is None


def test_insane_factor_rejected():
    with pytest.raises(RuleValidationError, match="sane range"):
        resolve_action({"type": "set_bid", "op": "multiply", "factor": 50}, 1.00)


def test_action_without_current_value_rejected():
    with pytest.raises(RuleValidationError, match="current value"):
        resolve_action({"type": "set_bid", "op": "multiply", "factor": 1.1}, None)


# ---------------------------------------------------------------- reasons
def test_reason_renders_with_percentages():
    text = render_reason(
        "ACOS {acos:.1%} vs break-even {break_even_acos:.1%} over {clicks} clicks",
        {"acos": 0.24, "break_even_acos": 0.35, "clicks": 42},
    )
    assert text == "ACOS 24.0% vs break-even 35.0% over 42 clicks"


def test_missing_metric_does_not_crash_the_run():
    text = render_reason("spend {cost} on {search_term}", {"cost": 12.5})
    assert "n/a" in text


def test_none_metric_does_not_crash_the_run():
    text = render_reason("ACOS {acos:.1%}", {"acos": None})
    assert isinstance(text, str)
