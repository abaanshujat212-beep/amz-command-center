"""The 7 starter CHANGE rules, expressed as DATA.

These are seeded disabled and in dry-run. Every threshold is relative to
break_even_acos (from sku_cost_ledger), never to a fixed ACOS number -- a 40%
ACOS is excellent on a 60% margin product and suicidal on a 15% margin one.

Each rule needs a reason_template because a recommendation nobody understands
is a recommendation nobody will approve.

Everything here proposes a change to the ads account. Rules that only report a
finding live in diagnostic_rules.py, and rule_catalog.py is what seeds both --
import ALL_RULES from there, never this list alone.

History worth keeping: flag_low_cvr_placement used to sit in this file with a
set_placement_modifier action, despite being named 'flag' and described as
"recommend only". It is now a diagnostic (#27).
"""

from __future__ import annotations

STARTER_RULES: list[dict] = [
    {
        "code": "scale_winners_budget",
        "name": "Scale winners: budget +20%",
        "description": "Campaign beating break-even and hitting its budget ceiling.",
        "scope": "campaign",
        "priority": 10,
        "lookback_days": 14,
        "min_clicks": 100,
        "min_impressions": 2000,
        "condition": {
            "and": [
                {"<": [{"var": "acos"}, {"*": [{"var": "break_even_acos"}, 0.8]}]},
                {">=": [{"var": "budget_utilisation"}, 0.9]},
                {">=": [{"var": "attributed_orders"}, 5]},
            ]
        },
        "action": {"type": "set_budget", "op": "multiply", "factor": 1.20},
        "reason_template": (
            "ACOS {acos:.1%} is below break-even {break_even_acos:.1%} and the campaign "
            "spent {budget_utilisation:.0%} of its {budget:.2f} budget on "
            "{days_capped} of {lookback_days} days. Raising budget by 20%."
        ),
    },
    {
        "code": "raise_bid_profitable",
        "name": "Raise bid on profitable keywords: +10%",
        "scope": "keyword",
        "priority": 20,
        "lookback_days": 14,
        "min_clicks": 15,
        "min_impressions": 500,
        "condition": {
            "and": [
                {"<": [{"var": "acos"}, {"*": [{"var": "break_even_acos"}, 0.7]}]},
                {">=": [{"var": "clicks"}, 15]},
                {">=": [{"var": "attributed_orders"}, 2]},
            ]
        },
        "action": {"type": "set_bid", "op": "multiply", "factor": 1.10},
        "reason_template": (
            "ACOS {acos:.1%} vs break-even {break_even_acos:.1%} over {clicks} clicks "
            "and {attributed_orders} orders. Room to bid up 10%."
        ),
    },
    {
        "code": "lower_bid_unprofitable",
        "name": "Lower bid on unprofitable keywords: -15%",
        "scope": "keyword",
        "priority": 20,
        "lookback_days": 14,
        "min_clicks": 15,
        "min_impressions": 500,
        "condition": {
            "and": [
                {">": [{"var": "acos"}, {"*": [{"var": "break_even_acos"}, 1.3]}]},
                {">=": [{"var": "clicks"}, 15]},
                {">": [{"var": "attributed_orders"}, 0]},
            ]
        },
        "action": {"type": "set_bid", "op": "multiply", "factor": 0.85},
        "reason_template": (
            "ACOS {acos:.1%} is {acos_ratio:.1f}x break-even {break_even_acos:.1%}. "
            "Still converting, so cutting bid 15% rather than pausing."
        ),
    },
    {
        "code": "pause_zero_order_keyword",
        "name": "Pause keywords with clicks but no orders",
        "scope": "keyword",
        "priority": 15,
        "lookback_days": 30,
        "min_clicks": 30,
        "min_impressions": 500,
        "condition": {
            "and": [
                {">=": [{"var": "clicks"}, 30]},
                {"==": [{"var": "attributed_orders"}, 0]},
                {">=": [{"var": "cost"}, 10]},
            ]
        },
        "action": {"type": "pause"},
        "reason_template": (
            "{clicks} clicks and {cost:.2f} spent over {lookback_days} days with zero "
            "orders. Pausing."
        ),
    },
    {
        "code": "negate_wasteful_search_term",
        "name": "Negative exact for wasteful search terms",
        "scope": "search_term",
        "priority": 15,
        "lookback_days": 30,
        "min_clicks": 20,
        "min_impressions": 200,
        "condition": {
            "and": [
                {">=": [{"var": "clicks"}, 20]},
                {"==": [{"var": "attributed_orders"}, 0]},
                {"==": [{"var": "is_already_negative"}, False]},
            ]
        },
        "action": {"type": "add_negative_exact", "level": "ad_group"},
        "reason_template": (
            "Search term '{search_term}' took {clicks} clicks and {cost:.2f} with no "
            "orders. Adding as negative exact."
        ),
    },
    {
        "code": "harvest_converting_search_term",
        "name": "Harvest converting search terms into exact",
        "scope": "search_term",
        "priority": 25,
        "lookback_days": 60,
        "min_clicks": 10,
        "min_impressions": 200,
        "condition": {
            "and": [
                {">=": [{"var": "attributed_orders"}, 3]},
                {"<": [{"var": "acos"}, {"var": "break_even_acos"}]},
                {"==": [{"var": "exists_as_exact"}, False]},
            ]
        },
        "action": {"type": "create_keyword", "match_type": "exact", "bid_source": "cpc_x_1_15"},
        "reason_template": (
            "'{search_term}' produced {attributed_orders} orders at {acos:.1%} ACOS from "
            "a broad/auto target. Promoting to exact and negating it in the source "
            "ad group."
        ),
    },
    {
        "code": "rescue_impression_starved",
        "name": "Rescue impression-starved profitable keywords: +15%",
        "scope": "keyword",
        "priority": 30,
        "lookback_days": 14,
        "min_clicks": 5,
        "min_impressions": 100,
        "condition": {
            "and": [
                {"<": [{"var": "impressions"}, 200]},
                {">": [{"var": "attributed_orders"}, 0]},
                {"<": [{"var": "acos"}, {"var": "break_even_acos"}]},
                {"<": [{"var": "top_of_search_is"}, 0.1]},
            ]
        },
        "action": {"type": "set_bid", "op": "multiply", "factor": 1.15},
        "reason_template": (
            "Profitable ({acos:.1%} ACOS) but only {impressions} impressions and "
            "{top_of_search_is:.1%} top-of-search share. Bidding up 15% to buy visibility."
        ),
    },
]


def rule_rows(tenant_id: str, created_by: str | None = None) -> list[dict]:
    """Shape STARTER_RULES for insertion into the `rule` table."""
    rows = []
    for r in STARTER_RULES:
        action = dict(r["action"])
        action["reason_template"] = r["reason_template"]
        rows.append(
            {
                "tenant_id": tenant_id,
                "code": r["code"],
                "name": r["name"],
                "description": r.get("description"),
                "enabled": False,   # never seed a live rule
                "dry_run": True,
                "priority": r["priority"],
                "scope": r["scope"],
                "condition_jsonb": r["condition"],
                "action_jsonb": action,
                "lookback_days": r["lookback_days"],
                "min_clicks": r["min_clicks"],
                "min_impressions": r["min_impressions"],
                "created_by": created_by,
            }
        )
    return rows
