/**
 * Drill-down and history read models.
 *
 * Same two rules as queries.ts, for the same reasons:
 *
 * 1. Marts are read through mart(), i.e. the copilot.* views, which carry the
 *    tenant filter inside the view definition. axaty_app holds no privilege on
 *    marts, so a forgotten filter is impossible rather than unlikely.
 *
 * 2. A rollup over N days recomputes every KPI from summed components and never
 *    averages a daily ratio.
 *
 * Rule 2 has a consequence that is easy to miss: a categorical column computed
 * per day cannot be rolled up either. mart_ppc_keyword_daily.verdict is one of
 * those. It is recomputed here from window sums, using the same thresholds as
 * the mart. Duplicating thresholds is a real cost, and it is still the lesser
 * evil -- picking a representative day's verdict would show 'losing' next to a
 * profitable window ACOS, which teaches the operator to ignore the column.
 */

import type { PoolClient } from "pg"
import { mart, query } from "./db"

/** Shared window predicate: settled days only, last $1 days. */
const WINDOW = `is_settled
		   and report_date >= current_date - ($1::int || ' days')::interval`

export type CampaignHeader = {
	campaign_id: string
	campaign_name: string
	campaign_status: string | null
	targeting_type: string | null
	budget_amount: number | null
	impressions: number
	clicks: number
	cost: number
	orders: number
	sales: number
	acos: number | null
	ctr: number | null
	cvr: number | null
	cpc: number | null
	break_even_acos: number | null
	economics_incomplete: boolean
	days: number
	data_through: string | null
}

export async function campaignHeader(
	client: PoolClient,
	campaignId: string,
	days = 30,
): Promise<CampaignHeader | null> {
	const rows = await query<CampaignHeader>(
		client,
		`
		with window_rows as (
			select *
			  from ${mart("mart_ppc_campaign_daily")}
			 where ${WINDOW}
			   and campaign_id = $2
		),
		latest as (
			select distinct on (campaign_id)
			       campaign_id, campaign_name, campaign_status, targeting_type,
			       budget_amount
			  from window_rows
			 order by campaign_id, report_date desc
		)
		select
			l.campaign_id, l.campaign_name, l.campaign_status, l.targeting_type,
			l.budget_amount,
			sum(w.impressions)          as impressions,
			sum(w.clicks)               as clicks,
			sum(w.cost)                 as cost,
			sum(w.attributed_orders_7d) as orders,
			sum(w.attributed_sales_7d)  as sales,
			case when sum(w.attributed_sales_7d) > 0
			     then sum(w.cost) / sum(w.attributed_sales_7d) end as acos,
			case when sum(w.impressions) > 0
			     then sum(w.clicks)::numeric / sum(w.impressions) end as ctr,
			case when sum(w.clicks) > 0
			     then sum(w.attributed_orders_7d)::numeric / sum(w.clicks) end as cvr,
			case when sum(w.clicks) > 0
			     then sum(w.cost) / sum(w.clicks) end as cpc,
			min(w.break_even_acos)          as break_even_acos,
			bool_or(w.economics_incomplete) as economics_incomplete,
			count(*)                        as days,
			max(w.report_date)::text        as data_through
		  from window_rows w
		  join latest l using (campaign_id)
		 group by l.campaign_id, l.campaign_name, l.campaign_status,
		          l.targeting_type, l.budget_amount
		`,
		[days, campaignId],
	)
	return rows[0] ?? null
}

export type KeywordRow = {
	keyword_id: string
	keyword_text: string
	match_type: string | null
	keyword_status: string | null
	ad_group_id: string
	bid: number | null
	impressions: number
	clicks: number
	cost: number
	orders: number
	sales: number
	acos: number | null
	ctr: number | null
	cvr: number | null
	cpc: number | null
	break_even_acos: number | null
	economics_incomplete: boolean
	top_of_search_impression_share: number | null
	verdict: string
	account_ctr: number | null
	account_cvr: number | null
}

/**
 * Keywords for one campaign, rolled up over the window.
 *
 * account_ctr / account_cvr are account-wide over the same window, not
 * campaign-wide, and they are returned on every row so the UI can say "this
 * keyword converts at half the account rate" without a second query. "Low CTR"
 * has no absolute value: 0.3% is normal for broad discovery and alarming for a
 * branded exact.
 */
export async function keywordPerformance(
	client: PoolClient,
	campaignId: string,
	days = 30,
	limit = 200,
): Promise<KeywordRow[]> {
	return query<KeywordRow>(
		client,
		`
		with all_rows as (
			select * from ${mart("mart_ppc_keyword_daily")} where ${WINDOW}
		),
		account as (
			select
				case when sum(impressions) > 0
				     then sum(clicks)::numeric / sum(impressions) end as account_ctr,
				case when sum(clicks) > 0
				     then sum(attributed_orders_7d)::numeric / sum(clicks) end as account_cvr
			  from all_rows
		),
		window_rows as (
			select * from all_rows where campaign_id = $2
		),
		latest as (
			select distinct on (keyword_id)
			       keyword_id, keyword_text, match_type, keyword_status,
			       ad_group_id, bid
			  from window_rows
			 order by keyword_id, report_date desc
		)
		select
			l.keyword_id, l.keyword_text, l.match_type, l.keyword_status,
			l.ad_group_id, l.bid,
			sum(w.impressions)          as impressions,
			sum(w.clicks)               as clicks,
			sum(w.cost)                 as cost,
			sum(w.attributed_orders_7d) as orders,
			sum(w.attributed_sales_7d)  as sales,
			case when sum(w.attributed_sales_7d) > 0
			     then sum(w.cost) / sum(w.attributed_sales_7d) end as acos,
			case when sum(w.impressions) > 0
			     then sum(w.clicks)::numeric / sum(w.impressions) end as ctr,
			case when sum(w.clicks) > 0
			     then sum(w.attributed_orders_7d)::numeric / sum(w.clicks) end as cvr,
			case when sum(w.clicks) > 0
			     then sum(w.cost) / sum(w.clicks) end as cpc,
			min(w.break_even_acos)          as break_even_acos,
			bool_or(w.economics_incomplete) as economics_incomplete,
			avg(w.top_of_search_impression_share) as top_of_search_impression_share,
			-- Recomputed from window sums. Thresholds mirror
			-- mart_ppc_keyword_daily; see the note at the top of this file.
			case
				when min(w.break_even_acos) is null then 'unknown'
				when sum(w.attributed_sales_7d) = 0 and sum(w.clicks) > 0 then 'no_sales'
				when sum(w.attributed_sales_7d) = 0 then 'no_data'
				when sum(w.cost) / sum(w.attributed_sales_7d)
				     <= min(w.break_even_acos) * 0.7 then 'strong'
				when sum(w.cost) / sum(w.attributed_sales_7d)
				     <= min(w.break_even_acos) then 'profitable'
				when sum(w.cost) / sum(w.attributed_sales_7d)
				     <= min(w.break_even_acos) * 1.3 then 'marginal'
				else 'losing'
			end as verdict,
			(select account_ctr from account) as account_ctr,
			(select account_cvr from account) as account_cvr
		  from window_rows w
		  join latest l using (keyword_id)
		 group by l.keyword_id, l.keyword_text, l.match_type, l.keyword_status,
		          l.ad_group_id, l.bid
		 order by sum(w.cost) desc
		 limit $3
		`,
		[days, campaignId, limit],
	)
}

export type SearchTermRow = {
	search_term: string
	campaign_id: string
	ad_group_id: string
	matched_keyword_text: string | null
	matched_match_type: string | null
	impressions: number
	clicks: number
	cost: number
	orders: number
	sales: number
	acos: number | null
	ctr: number | null
	cvr: number | null
	cpc: number | null
	break_even_acos: number | null
	is_already_negative: boolean
	exists_as_exact: boolean
}

/**
 * Customer search terms, rolled up over the window.
 *
 * is_already_negative and exists_as_exact are carried through with bool_or so
 * the UI can grey out a term that is already handled. Without them this screen
 * invites the operator to negate the same term every week and wonder why
 * nothing changes.
 */
export async function searchTermPerformance(
	client: PoolClient,
	days = 30,
	campaignId: string | null = null,
	limit = 200,
): Promise<SearchTermRow[]> {
	return query<SearchTermRow>(
		client,
		`
		with window_rows as (
			select *
			  from ${mart("mart_ppc_search_term_daily")}
			 where ${WINDOW}
			   and ($2::text is null or campaign_id = $2)
		)
		select
			search_term,
			min(campaign_id)  as campaign_id,
			min(ad_group_id)  as ad_group_id,
			min(matched_keyword_text) as matched_keyword_text,
			min(matched_match_type)   as matched_match_type,
			sum(impressions)          as impressions,
			sum(clicks)               as clicks,
			sum(cost)                 as cost,
			sum(attributed_orders_7d) as orders,
			sum(attributed_sales_7d)  as sales,
			case when sum(attributed_sales_7d) > 0
			     then sum(cost) / sum(attributed_sales_7d) end as acos,
			case when sum(impressions) > 0
			     then sum(clicks)::numeric / sum(impressions) end as ctr,
			case when sum(clicks) > 0
			     then sum(attributed_orders_7d)::numeric / sum(clicks) end as cvr,
			case when sum(clicks) > 0
			     then sum(cost) / sum(clicks) end as cpc,
			min(break_even_acos)          as break_even_acos,
			bool_or(is_already_negative)  as is_already_negative,
			bool_or(exists_as_exact)      as exists_as_exact
		  from window_rows
		 group by search_term
		 order by sum(cost) desc
		 limit $3
		`,
		[days, campaignId, limit],
	)
}

export type HistoryRow = {
	id: string
	entity_type: string
	entity_id: string
	action_type: string
	before_value: unknown
	after_value: unknown
	status: string
	decision: string | null
	decided_at: string | null
	decided_by: string | null
	applied_at: string | null
	verified_at: string | null
	rolled_back_at: string | null
	outcome: string | null
	error: string | null
	reason_text: string | null
	rule_code: string | null
	rule_name: string | null
	sort_at: string
}

/**
 * Everything that has already been decided: applied, verified, failed,
 * rolled back, rejected, expired.
 *
 * Ordering uses decided_at (0009) and falls back to requested_at only for rows
 * no human ever decided -- an expiry. Using coalesce the other way round would
 * invent a decision time for those rows, which is precisely the kind of
 * plausible-but-false number this project keeps having to remove.
 *
 * error is included because a failed write-back is the single most important row
 * on this screen: drift: means Amazon's live value no longer matched the
 * proposal, so the action refused rather than overwriting someone's change.
 */
export async function actionHistory(
	client: PoolClient,
	days = 30,
	limit = 200,
): Promise<HistoryRow[]> {
	return query<HistoryRow>(
		client,
		`
		select a.id, a.entity_type, a.entity_id, a.action_type,
		       a.before_value, a.after_value, a.status,
		       a.decision, a.decided_at::text as decided_at, a.decided_by::text as decided_by,
		       a.applied_at::text as applied_at,
		       a.verified_at::text as verified_at,
		       a.rolled_back_at::text as rolled_back_at,
		       a.outcome, a.error, a.reason_text,
		       r.code as rule_code, r.name as rule_name,
		       coalesce(a.decided_at, a.requested_at)::text as sort_at
		  from action a
		  left join rule r on r.id = a.rule_id
		 where a.action_type <> 'flag'
		   and a.status in ('approved','applied','verified','failed',
		                    'rolled_back','rejected','expired')
		   and coalesce(a.decided_at, a.requested_at)
		       >= now() - ($1::int || ' days')::interval
		 order by coalesce(a.decided_at, a.requested_at) desc
		 limit $2
		`,
		[days, limit],
	)
}

export type HistoryTotals = {
	status: string
	n: number
	spend_delta: number | null
}

/**
 * Counts by status for the history header.
 *
 * spend_delta only sums rows that actually reached Amazon (applied, verified).
 * Counting proposed deltas would describe a budget change that never happened.
 */
export async function historyTotals(
	client: PoolClient,
	days = 30,
): Promise<HistoryTotals[]> {
	return query<HistoryTotals>(
		client,
		`
		select a.status,
		       count(*) as n,
		       sum(
		         case when a.status in ('applied','verified')
		                   and a.action_type in ('set_bid','set_budget')
		              then (a.after_value->>'value')::numeric
		                 - coalesce((a.before_value->>'value')::numeric, 0)
		         end
		       ) as spend_delta
		  from action a
		 where a.action_type <> 'flag'
		   and coalesce(a.decided_at, a.requested_at)
		       >= now() - ($1::int || ' days')::interval
		 group by a.status
		 order by count(*) desc
		`,
		[days],
	)
}
