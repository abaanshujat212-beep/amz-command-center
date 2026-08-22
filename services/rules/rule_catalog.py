"""The single source of truth for which rules a new tenant gets.

seed.py used to import rule_rows() from starter_rules, which meant the set of
seeded rules was whatever happened to live in that one file. Diagnostics live
in their own module (they are a different kind of thing), so the catalog is
assembled here and seeding imports from here only.
"""

from __future__ import annotations

from services.rules.diagnostic_rules import DIAGNOSTIC_RULES
from services.rules.starter_rules import STARTER_RULES

ALL_RULES: list[dict] = [*STARTER_RULES, *DIAGNOSTIC_RULES]


def _assert_unique_codes(rules: list[dict]) -> None:
    """`rule` has a unique (tenant_id, code) index.

    Without this check a duplicated code fails at INSERT time inside a seed
    transaction, halfway through a tenant, instead of at import time.
    """
    seen: set[str] = set()
    dupes = sorted({r["code"] for r in rules if r["code"] in seen or seen.add(r["code"])})
    if dupes:
        raise ValueError(f"duplicate rule codes in the catalog: {dupes}")


_assert_unique_codes(ALL_RULES)


def shape_rule(rule: dict, tenant_id: str, created_by: str | None = None) -> dict:
    """Shape one catalog entry for insertion into the `rule` table."""
    action = dict(rule["action"])
    action["reason_template"] = rule["reason_template"]
    return {
        "tenant_id": tenant_id,
        "code": rule["code"],
        "name": rule["name"],
        "description": rule.get("description"),
        "enabled": False,   # never seed a live rule
        "dry_run": True,
        "priority": rule["priority"],
        "scope": rule["scope"],
        "condition_jsonb": rule["condition"],
        "action_jsonb": action,
        "lookback_days": rule["lookback_days"],
        "min_clicks": rule["min_clicks"],
        "min_impressions": rule["min_impressions"],
        "created_by": created_by,
    }


def all_rule_rows(tenant_id: str, created_by: str | None = None) -> list[dict]:
    """Every rule a new tenant should start with, disabled and in dry-run."""
    return [shape_rule(r, tenant_id, created_by) for r in ALL_RULES]
