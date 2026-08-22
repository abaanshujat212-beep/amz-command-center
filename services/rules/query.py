"""Build the candidate query for a rule.

Two things here are easy to get wrong and expensive to get wrong:

1. AGGREGATE FIRST, THEN TEST. A rule saying "15 clicks" means 15 clicks over
   the lookback window, not 15 in one day. Testing per-day rows would fire on
   noise and propose a change every single day.

2. The compiled condition must run INSIDE SQL over those aggregates. An earlier
   version returned every aggregated row and let Python assume they all matched,
   which silently turned every rule into "match everything".

Column aliases here must match compiler.METRICS exactly, because that is how the
compiled SQL refers to them (m.acos, e.break_even_acos, ...). Every metric in
METRICS must be produced by EVERY scope, even as a typed null placeholder --
otherwise a rule referencing it fails to resolve the column at run time instead
of at authoring time.

A scope missing from SCOPE_SOURCES is not an error the engine can fix: it skips
the rule with a note and carries on. That is how flag_low_cvr_placement sat
dead for a whole milestone (Defect D, issue #27), so tests assert that every
rule in the catalog has a wired scope.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

# scope -> (mart table, entity id column, the column a change writes to)
#
# placement's write target is placement_modifier_pct, which the mart currently
# publishes as NULL because campaign placement-bidding config is not ingested
# yet (#32). That null is load-bearing: it makes an add_pct action refuse for
# want of a current value instead of assuming 0% and overwriting a real
# modifier the seller set by hand.
SCOPE_SOURCES: dict[str, tuple[str, str, str]] = {
    "campaign": ("mart_ppc_campaign_daily", "campaign_id", "budget_amount"),
    "keyword": ("mart_ppc_keyword_daily", "keyword_id", "bid"),
    "search_term": ("mart_ppc_search_term_daily", "search_term", "bid"),
    "placement": ("mart_ppc_placement_daily", "placement_entity_id", "placement_modifier_pct"),
}

# Metrics every scope can produce.
_COMMON_AGG = """
    sum(clicks)                                   as clicks,
    sum(impressions)                              as impressions,
    sum(cost)                                     as cost,
    sum(attributed_orders_7d)                     as attributed_orders_7d,
    sum(attributed_sales_7d)                      as attributed_sales_7d,
    sum(attributed_units_7d)                      as attributed_units_7d,
    min(break_even_acos)                          as break_even_acos,
    case when sum(attributed_sales_7d) > 0
         then sum(cost) / sum(attributed_sales_7d) end as acos,
    case when sum(cost) > 0
         then sum(attributed_sales_7d) / sum(cost) end as roas,
    case when sum(impressions) > 0
         then sum(clicks)::numeric / sum(impressions) end as ctr,
    case when sum(clicks) > 0
         then sum(attributed_orders_7d)::numeric / sum(clicks) end as cvr,
    case when sum(clicks) > 0 then sum(cost) / sum(clicks) end as cpc
"""

# Scope-specific extras. Anything a rule might reference must exist here, even
# as a null placeholder, or the compiled SQL will fail to resolve the column.
_SCOPE_AGG: dict[str, str] = {
    "campaign": """
        max(budget_amount)                        as budget_amount,
        avg(budget_utilisation)                   as budget_utilisation,
        count(*) filter (where budget_utilisation >= 0.98) as days_capped,
        null::numeric                             as bid,
        null::numeric                             as top_of_search_impression_share,
        null::numeric                             as account_cvr,
        null::numeric                             as account_ctr,
        null::numeric                             as contribution_margin_pct,
        null::numeric                             as tacos,
        false                                     as is_already_negative,
        false                                     as exists_as_exact
    """,
    "keyword": """
        max(bid)                                  as bid,
        avg(top_of_search_impression_share)       as top_of_search_impression_share,
        avg(account_cvr)                          as account_cvr,
        avg(account_ctr)                          as account_ctr,
        min(contribution_margin_pct)              as contribution_margin_pct,
        null::numeric                             as budget_amount,
        null::numeric                             as budget_utilisation,
        null::numeric                             as days_capped,
        null::numeric                             as tacos,
        false                                     as is_already_negative,
        false                                     as exists_as_exact
    """,
    "search_term": """
        max(bid)                                  as bid,
        bool_or(is_already_negative)              as is_already_negative,
        bool_or(exists_as_exact)                  as exists_as_exact,
        null::numeric                             as budget_amount,
        null::numeric                             as budget_utilisation,
        null::numeric                             as days_capped,
        null::numeric                             as top_of_search_impression_share,
        null::numeric                             as account_cvr,
        null::numeric                             as account_ctr,
        null::numeric                             as contribution_margin_pct,
        null::numeric                             as tacos
    """,
    # Placement inherits the campaign's economics and budget (the mart joins
    # them from mart_ppc_campaign_daily), so a placement rule can still reason
    # about break-even and budget pressure. bid is null: a placement has no bid,
    # only a percentage modifier on the campaign's bids.
    "placement": """
        avg(account_cvr)                          as account_cvr,
        avg(account_ctr)                          as account_ctr,
        min(contribution_margin_pct)              as contribution_margin_pct,
        max(budget_amount)                        as budget_amount,
        avg(budget_utilisation)                   as budget_utilisation,
        count(*) filter (where budget_utilisation >= 0.98) as days_capped,
        null::numeric                             as bid,
        null::numeric                             as top_of_search_impression_share,
        null::numeric                             as tacos,
        false                                     as is_already_negative,
        false                                     as exists_as_exact
    """,
}


def build_candidate_sql(scope: str, where_sql: str) -> str:
    table, id_col, value_col = SCOPE_SOURCES[scope]
    return f"""
        with agg as (
            select
                {id_col}::text as entity_id,
                max({value_col}) as current_value,
                {_COMMON_AGG.strip()},
                {_SCOPE_AGG[scope].strip()}
            from marts.{table}
            where tenant_id = %s
              and report_date >  %s - (%s * interval '1 day')
              and report_date <= %s
              and is_settled
            group by 1
        )
        select
            m.*,
            ({where_sql}) as matched
        from agg m,
        lateral (
            select m.break_even_acos        as break_even_acos,
                   m.contribution_margin_pct as contribution_margin_pct
        ) e
    """


def fetch_candidates(
    cur,
    *,
    tenant_id: str,
    scope: str,
    lookback_days: int,
    through: dt.date,
    where_sql: str,
    where_params: list[Any],
) -> list[dict]:
    """Return aggregated entities with a boolean `matched` column.

    Params order matters: the CTE's placeholders come first because the CTE
    appears before the condition in the statement text.
    """
    sql = build_candidate_sql(scope, where_sql)
    params = [tenant_id, through, lookback_days, through, *where_params]
    cur.execute(sql, params)
    return cur.fetchall()
