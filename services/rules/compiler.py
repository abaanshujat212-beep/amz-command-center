"""Compile a rule's JSONB condition into parameterised SQL.

Security posture: rules are user-editable data that end up inside a SQL query.
That is an injection surface, so nothing is trusted:

  * variables must be in METRICS -- the column name comes from OUR map, never
    from the rule text
  * operators must be in OPS
  * every literal is bound as a parameter, never interpolated
  * expression depth and node count are capped

If a rule cannot be compiled it is rejected loudly. A rule that half-works is
more dangerous than one that does not run.
"""

from __future__ import annotations

from typing import Any

from services.rules.guardrails import DIAGNOSTIC_ACTIONS

MAX_DEPTH = 8
MAX_NODES = 120

# Whitelisted metric -> real column in the mart. The rule never names a column.
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
    # Account-wide benchmarks. Diagnostics compare an entity to the account
    # rather than to a fixed number, because "good CTR" is category-specific:
    # 0.3% is fine for a broad term and terrible for a branded exact.
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

# Keys that mean "change something". A diagnostic carrying any of these is a
# misconfigured rule, not a harmless one -- see _assert_diagnostic_is_inert.
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

        # literals
        if node is None or isinstance(node, (bool, int, float)):
            return self._param(node)
        if isinstance(node, str):
            # bare strings are literals; identifiers only ever arrive via {"var": ...}
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
                raise RuleValidationError(
                    f"unknown metric '{args}'. Allowed: {sorted(METRICS)}"
                )
            return METRICS[args]          # from our map, never from rule text

        if op not in OPS:
            raise RuleValidationError(f"operator '{op}' is not allowed")

        if op == "not":
            inner = args[0] if isinstance(args, list) else args
            return f"(not {self.compile(inner, depth + 1)})"

        if not isinstance(args, list) or len(args) < 2:
            raise RuleValidationError(f"operator '{op}' needs a list of >= 2 operands")

        if op in LOGICAL:
            joined = f" {LOGICAL[op]} ".join(
                self.compile(a, depth + 1) for a in args
            )
            return f"({joined})"

        if op in COMPARISONS:
            if len(args) != 2:
                raise RuleValidationError(f"'{op}' takes exactly 2 operands")
            left = self.compile(args[0], depth + 1)
            right = self.compile(args[1], depth + 1)
            # A null metric means "unknown", and unknown must never satisfy a
            # condition -- otherwise a keyword with no clicks looks perfect.
            return f"({left} is not null and {right} is not null and {left} {COMPARISONS[op]} {right})"

        joined = f" {ARITHMETIC[op]} ".join(self.compile(a, depth + 1) for a in args)
        if op == "/":
            # never divide by zero inside a rule
            parts = [self.compile(a, depth + 1) for a in args]
            return f"({parts[0]} / nullif({parts[1]}, 0))"
        return f"({joined})"


def compile_condition(condition: dict) -> tuple[str, list[Any]]:
    """Return (sql_boolean_expression, params)."""
    if not isinstance(condition, dict) or not condition:
        raise RuleValidationError("condition must be a non-empty object")
    c = _Compiler()
    sql = c.compile(condition)
    return sql, c.params


def validate(condition: dict) -> None:
    """Raise if the condition would not compile. Call before saving a rule."""
    compile_condition(condition)


# --------------------------------------------------------------- action side
def _assert_diagnostic_is_inert(action: dict) -> None:
    """A diagnostic must carry no instruction to change anything.

    Cheap to check, and the failure it prevents is expensive: a rule authored
    as {"type": "flag", "op": "multiply", "factor": 0.5} would read as harmless
    in the UI while the apply path found a real op to execute.
    """
    present = [k for k in MUTATION_KEYS if k in action]
    if present:
        raise RuleValidationError(
            f"diagnostic action '{action.get('type')}' must not carry "
            f"mutation keys {present}; diagnostics only report"
        )


def resolve_action(action: dict, current_value: float | None) -> float | None:
    """Turn an action descriptor + current value into a target value.

    Returns None for actions that carry no numeric value (pause, negatives,
    diagnostics). Guardrails still clamp whatever comes out of here.
    """
    kind = action.get("type")

    # Diagnostics resolve to no value at all. They are checked first so that a
    # flag rule can never take the "needs a current value" path below and be
    # silently dropped from the run.
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


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "n/a"


def render_reason(template: str, metrics: dict[str, Any]) -> str:
    """Render the human explanation. A missing metric must not crash a run."""
    try:
        return template.format_map(_SafeDict(metrics))
    except (ValueError, TypeError):
        # e.g. '{acos:.1%}' when acos is None
        safe = {k: (v if v is not None else 0) for k, v in metrics.items()}
        try:
            return template.format_map(_SafeDict(safe))
        except Exception:
            return template
