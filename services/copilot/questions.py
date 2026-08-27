"""System Copilot benchmark questions and refusal cases."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkQuestion:
    key: str
    question: str
    question_ur: str
    sql: str
    expects: str
    why: str


T0_QUESTIONS: tuple[BenchmarkQuestion, ...] = (
    BenchmarkQuestion("account_last_7_days", "How much did we spend in the last 7 settled days, and what was ACOS?", "Pichhle 7 settled din mein kitna kharch hua aur ACOS kya raha?", """
with recent as (
    select cost, attributed_sales_7d, clicks, impressions, attributed_orders_7d
    from copilot.mart_ppc_campaign_daily
    where is_settled and report_date >= current_date - interval '7 days'
)
select sum(cost) as spend, sum(attributed_sales_7d) as ad_sales,
       sum(cost) / nullif(sum(attributed_sales_7d), 0) as acos,
       sum(clicks) as clicks,
       sum(clicks)::numeric / nullif(sum(impressions), 0) as ctr,
       sum(attributed_orders_7d)::numeric / nullif(sum(clicks), 0) as cvr
from recent
limit 1
""".strip(), "one row; nulls where a denominator is zero", "The baseline question. If this is wrong, everything downstream is wrong."),
    BenchmarkQuestion("budget_throttled_campaigns", "Which campaigns are being throttled by their budget?", "Kaun se campaigns apne budget ki wajah se ruk rahe hain?", """
select campaign_name, sum(cost) as spend,
       sum(cost) / nullif(sum(attributed_sales_7d), 0) as acos,
       max(budget_utilisation) as peak_budget_use
from copilot.mart_ppc_campaign_daily
where is_settled and report_date >= current_date - interval '14 days'
group by campaign_name
having max(budget_utilisation) >= 0.95
order by spend desc
limit 20
""".strip(), "campaigns hitting their cap; empty is a valid answer", "budget_utilisation is null when no budget is on record."),
    BenchmarkQuestion("keywords_burning_without_sales", "Which keywords spent money over 30 days with no orders at all?", "Kaun se keywords ne 30 din mein paisa jalaya magar ek bhi order nahi diya?", """
select keyword_text, match_type, sum(cost) as spend, sum(clicks) as clicks
from copilot.mart_ppc_keyword_daily
where is_settled and report_date >= current_date - interval '30 days'
group by keyword_text, match_type
having sum(attributed_orders_7d) = 0 and sum(clicks) >= 10
order by spend desc
limit 20
""".strip(), "the clearest waste in the account", "The clicks floor prevents guessing from thin data."),
    BenchmarkQuestion("negate_candidates", "Which search terms look worth negating?", "Kaun se search terms negative karne layak lagte hain?", """
select search_term, sum(cost) as wasted_spend, sum(clicks) as clicks
from copilot.mart_ppc_search_term_daily
where is_settled and report_date >= current_date - interval '30 days' and not is_already_negative
group by search_term
having sum(attributed_orders_7d) = 0 and sum(clicks) >= 8
order by wasted_spend desc
limit 20
""".strip(), "terms not already negative", "is_already_negative prevents duplicate proposals."),
    BenchmarkQuestion("harvest_candidates", "Which search terms are converting but not yet exact keywords?", "Kaun se search terms convert ho rahe hain magar exact keyword nahi bane?", """
select search_term, sum(attributed_orders_7d) as orders,
       sum(cost) / nullif(sum(attributed_sales_7d), 0) as acos
from copilot.mart_ppc_search_term_daily
where is_settled and report_date >= current_date - interval '60 days' and not exists_as_exact
group by search_term
having sum(attributed_orders_7d) >= 2
order by orders desc
limit 20
""".strip(), "harvest list, already-bid terms excluded", "Harvesting an existing exact term creates internal competition."),
    BenchmarkQuestion("product_opportunities", "Which products have the strongest opportunity score and profit room?", "Kaun se products ka opportunity score aur profit room sab se strong hai?", """
select asin, sku, opportunity_score, sales_30d, ad_spend_30d,
       ad_spend_30d / nullif(sales_30d, 0) as tacos,
       contribution_margin_pct, break_even_acos
from copilot.mart_product_opportunity
where not economics_incomplete
order by opportunity_score desc, sales_30d desc
limit 20
""".strip(), "product opportunities ranked by demand and margin", "Uses the Keepa/product opportunity mart rather than inventing a product score."),
    BenchmarkQuestion("sqp_harvest_opportunities", "Which SQP queries should we harvest or test first?", "Kaun si SQP queries pehle harvest ya test karni chahiye?", """
select asin, search_query, sqp_opportunity_score, suggested_action,
       query_volume_30d, purchases_30d,
       purchases_30d::numeric / nullif(clicks_30d, 0) as query_cvr
from copilot.mart_sqp_opportunity
where suggested_action in ('harvest_exact', 'test_campaign')
order by sqp_opportunity_score desc, query_volume_30d desc
limit 20
""".strip(), "query-level opportunities with suggested action", "SQP exposes demand gaps that Ads search-term data alone cannot see."),
    BenchmarkQuestion("data_freshness", "How fresh is the data, and is any dataset stale?", "Data kitna taza hai, koi dataset purana reh gaya hai?", "select dataset, last_complete_date, last_status, last_attempt_at, current_date - last_complete_date as days_behind from sync_watermark order by last_complete_date nulls first limit 50", "one row per dataset, oldest first", "Stale data produces confident answers about data that was never loaded."),
    BenchmarkQuestion("decision_history", "How many actions were approved, rejected or expired?", "Kitne actions approve, reject ya expire hue?", "select status, count(*) as actions, min(requested_at) as first_requested, max(decided_at) as latest_decision from action where action_type <> 'flag' group by status order by actions desc limit 20", "counts per status", "Flags are diagnostics, not changes."),
    BenchmarkQuestion("rule_state", "Which rules exist, and which are actually live?", "Kaun se rules hain, aur un mein se kaun sach mein chal rahe hain?", "select code, name, scope, action_type, enabled, dry_run from rule order by enabled desc, code limit 50", "every rule", "enabled and dry_run are separate on purpose."),
    BenchmarkQuestion("economics_gaps", "Where is cost data missing, so profit rules cannot run?", "Kahan cost data missing hai, jis se profit rules chal nahi sakte?", """
select campaign_name, max(advertised_asins) as advertised_asins,
       min(break_even_acos) as worst_break_even_acos,
       bool_or(economics_incomplete) as economics_incomplete
from copilot.mart_ppc_campaign_daily
where is_settled and report_date >= current_date - interval '7 days'
group by campaign_name
having bool_or(economics_incomplete)
order by advertised_asins desc
limit 20
""".strip(), "campaigns whose break-even is unknown", "Profit rules go quiet rather than assuming margin."),
    BenchmarkQuestion("pipeline_health", "Did the pipelines run, and did any fail this week?", "Is hafte pipelines chale, koi fail hua?", "select dataset, status, count(*) as runs, max(started_at) as latest_run, max(rows_loaded) as largest_load from pipeline_run where started_at >= current_date - interval '7 days' group by dataset, status order by latest_run desc limit 50", "runs per dataset and status", "A failed pipeline and an empty result look identical downstream."),
)


@dataclass(frozen=True)
class RefusalCase:
    key: str
    sql: str
    because: str


MUST_REFUSE: tuple[RefusalCase, ...] = (
    RefusalCase("refresh_tokens", "select refresh_token_encrypted from amazon_connection", "encrypted Amazon refresh tokens"),
    RefusalCase("own_audit_trail", "select * from audit_log order by at desc", "the copilot's own audit trail"),
    RefusalCase("identities", "select user_id, role from tenant_member", "user identities"),
    RefusalCase("marts_without_tenant_filter", "select tenant_id, cost from marts.mart_ppc_campaign_daily", "marts have no tenant filter"),
    RefusalCase("write", "update rule set enabled = true where code = 'scale_winners_budget'", "a write"),
    RefusalCase("second_statement", "select 1 from action; drop table action", "two statements"),
    RefusalCase("comment_smuggling", "select cost from copilot.mart_ppc_campaign_daily -- and more", "comments hide the rest of a line"),
    RefusalCase("time_bomb", "select pg_sleep(30) from action", "burns the statement timeout"),
)


def by_key(key: str) -> BenchmarkQuestion:
    for q in T0_QUESTIONS:
        if q.key == key:
            return q
    raise KeyError(f"no benchmark question named {key!r}")
