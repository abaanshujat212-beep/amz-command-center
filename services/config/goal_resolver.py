"""Authoritative effective PPC-goal resolution with per-value provenance."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

SCOPE_PRECEDENCE = (
    "account",
    "portfolio",
    "product_family",
    "asin",
    "campaign",
    "ad_group",
    "target",
    "keyword",
)
GOAL_FIELDS = (
    "target_acos",
    "min_acos",
    "max_acos",
    "target_roas",
    "acos_ceiling",
    "profit_floor",
)


@dataclass(frozen=True)
class GoalSource:
    scope_type: str
    scope_id: str
    override_id: str


@dataclass(frozen=True)
class EffectiveGoal:
    values: Mapping[str, Decimal | None]
    sources: Mapping[str, GoalSource | None]
    as_of: dt.date


def resolve_effective_goal(
    conn,
    *,
    tenant_id: str,
    scopes: Mapping[str, str],
    as_of: dt.date | None = None,
) -> EffectiveGoal:
    """Resolve each goal field from the most-specific active override."""
    unknown = set(scopes).difference(SCOPE_PRECEDENCE)
    if unknown:
        raise ValueError(f"unsupported PPC goal scope(s): {', '.join(sorted(unknown))}")
    normalized = {key: str(value).strip() for key, value in scopes.items()}
    if not normalized.get("account"):
        raise ValueError("account scope is required")
    if any(not value for value in normalized.values()):
        raise ValueError("PPC goal scope ids cannot be blank")

    resolved_on = as_of or dt.date.today()
    rows = conn.execute(
        """select id,scope_type,scope_id,target_acos,min_acos,max_acos,
                  target_roas,acos_ceiling,profit_floor
             from ppc_goal_override
            where tenant_id=%s
              and scope_type=any(%s)
              and scope_id=any(%s)
              and effective_from <= %s
              and (effective_to is null or effective_to >= %s)""",
        (
            tenant_id,
            list(normalized),
            list(normalized.values()),
            resolved_on,
            resolved_on,
        ),
    ).fetchall()
    active = {
        row["scope_type"]: row
        for row in rows
        if normalized.get(row["scope_type"]) == row["scope_id"]
    }
    values: dict[str, Decimal | None] = {field: None for field in GOAL_FIELDS}
    sources: dict[str, GoalSource | None] = {field: None for field in GOAL_FIELDS}
    for scope_type in reversed(SCOPE_PRECEDENCE):
        row = active.get(scope_type)
        if row is None:
            continue
        for field in GOAL_FIELDS:
            if values[field] is None and row[field] is not None:
                values[field] = row[field]
                sources[field] = GoalSource(scope_type, row["scope_id"], str(row["id"]))
    return EffectiveGoal(values=values, sources=sources, as_of=resolved_on)
