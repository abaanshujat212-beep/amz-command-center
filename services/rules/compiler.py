"""Compile a rule's JSONB condition into parameterised SQL."""

from __future__ import annotations

from typing import Any

from services.rules.guardrails import DIAGNOSTIC_ACTIONS

MAX_DEPTH = 8
MAX_NODES = 120

METRICS: dict[str, str] = {
    "acos": "m.acos",
    "roas": "m.roas",
    "ctr": "m.ctr",
    "cvr": "m.cvr",
    "cpc": "m.cpc",
    "tacos": "m.tacos",
    "clicks": "m.clicks",
    "impressions": "m.impressions",
    "cost": "m.cost",
    "attributed_sales": "m.attributed_sales_7d",
    "attributed_orders": "m.attributed_orders_7d",
    "attributed_units": "m.attributed_units_7d",
    "bid": "m.bid",
    "budget": "m.budget_amount",
    "budget_utilisation": "m.budget_utilisation",
    "days_capped": "m.days_capped",
    "top_of_search_is": "m.top_of_search_impression_share",
    "account_cvr": "m.account_cvr",
    "account_ctr": "m.account_ctr",
    "break_even_acos": "e.break_even_acos",
    "contribution_margin_pct": "e.contribution_margin_pct",
    "is_already_negative": "m.is_already_negative",
    "exists_as_exact": "m.exists_as_exact",
}

COMPARISONS = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "==": "=", "!=": "<>"}
ARITHMETIC = {"+": "+", "-": "-", "*": "*", "/": "/"}
LOGICAL = {"and": "and", "or": "or"}
OPS = set(COMPARISONS) | set(ARITHMETIC) | set(LOGICAL) | {"not"}
MUTATION_KEYS = ("op", "factor", "delta", "delta_pct", "value", "match_type", "level")


class RuleValidationError(ValueError):
    """The rule is malformed, unsafe, or references something unknown."""


class _Compiler:
    def __init__(self) -> None:
        self.params: list[Any] = []
        self.nodes = 0

    def _param(self, value: Any) -> str:
        self.params.append(value)
        return "%s"

    def compile(self, node: Any, depth: int = 0) -> str:
        self.nodes += 1
        if depth > MAX_DEPTH:
            raise RuleValidationError(f"expression nested deeper than {MAX_DEPTH}")
        if self.nodes > MAX_NODES:
            raise RuleValidationError(f"expression has more than {MAX_NODES} nodes")
        if node is None or isinstance(node, (bool, int, float)):
            return self._param(node)
        if isinstance(node, str):
            return self._param(node)
        if not isinstance(node, dict):
            raise RuleValidationError(f"unsupported node type {type(node).__name__}")
        if len(node) != 1:
            raise RuleValidationError(f"expected exactly one operator, got {list(node)}")

        op, args = next(iter(node.items()))
        if op == "var":
            if not isinstance(args, str):
                raise RuleValidationError("'var' takes a metric name string")
            if args not in METRICS:
                raise RuleValidationError(f"unknown metric '{args}'. Allowed: {sorted(METRICS)}")
            return METRICS[args]
        if op not in OPS:
            raise RuleValidationError(f"operator '{op}' is not allowed")
        if op == "not":
            inner = args[0] if isinstance(args, list) else args
            return f"(not {self.compile(inner, depth + 1)})"
        if not isinstance(args, list) or len(args) < 2:
            raise RuleValidationError(f"operator '{op}' needs a list of >= 2 operands")
        if op in LOGICAL:
            joined = f" {LOGICAL[op]} ".join(self.compile(a, depth + 1) for a in args)
            return f"({joined})"
        if op in COMPARISONS:
            if len(args) != 2:
                raise RuleValidationError(f"'{op}' takes exactly 2 operands")
            left = self.compile(args[0], depth + 1)
            right = self.compile(args[1], depth + 1)
            # SQL comparisons already yield NULL when either side is NULL.
            # Coalesce that to false while referencing each bound parameter only
            # once; repeating `%s` text without repeating params breaks psycopg.
            return f"coalesce(({left} {COMPARISONS[op]} {right}), false)"
        if op == "/":
            parts = [self.compile(a, depth + 1) for a in args]
            return f"({parts[0]} / nullif({parts[1]}, 0))"
        joined = f" {ARITHMETIC[op]} ".join(self.compile(a, depth + 1) for a in args)
        return f"({joined})"


def compile_condition(condition: dict) -> tuple[str, list[Any]]:
    if not isinstance(condition, dict) or not condition:
        raise RuleValidationError("condition must be a non-empty object")
    c = _Compiler()
    sql = c.compile(condition)
    return sql, c.params


def validate(condition: dict) -> None:
    compile_condition(condition)


def _assert_diagnostic_is_inert(action: dict) -> None:
    present = [k for k in MUTATION_KEYS if k in action]
    if present:
        raise RuleValidationError(
            f"diagnostic action '{action.get('type')}' must not carry mutation keys {present}; diagnostics only report"
        )


def resolve_action(action: dict, current_value: float | None) -> float | None:
    kind = action.get("type")
    if kind in DIAGNOSTIC_ACTIONS:
        _assert_diagnostic_is_inert(action)
        return None
    if kind in ("pause", "enable", "add_negative_exact", "add_negative_phrase"):
        return None
    op = action.get("op")
    if op is None and kind == "create_keyword":
        return None
    if current_value is None:
        raise RuleValidationError(f"action '{kind}' needs a current value to change")
    if op == "multiply":
        factor = float(action["factor"])
        if not 0.1 <= factor <= 3.0:
            raise RuleValidationError(f"factor {factor} is outside the sane range 0.1-3.0")
        return round(current_value * factor, 2)
    if op == "add":
        return round(current_value + float(action["delta"]), 2)
    if op == "add_pct":
        return round(current_value * (1 + float(action["delta_pct"]) / 100), 2)
    if op == "set":
        return round(float(action["value"]), 2)
    raise RuleValidationError(f"unknown action op '{op}'")


class _MissingMetric:
    def __format__(self, spec: str) -> str:
        return "n/a"

    def __str__(self) -> str:
        return "n/a"


class _SafeDict(dict):
    def __missing__(self, key: str) -> _MissingMetric:
        return _MissingMetric()


def render_reason(template: str, metrics: dict[str, Any]) -> str:
    try:
        return template.format_map(_SafeDict(metrics))
    except (ValueError, TypeError):
        safe = {k: (v if v is not None else _MissingMetric()) for k, v in metrics.items()}
        try:
            return template.format_map(_SafeDict(safe))
        except Exception:
            return template
