import type { PoolClient } from "pg"
import { mart, query } from "./db"

export type CampaignRow = {
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
	roas: number | null
	ctr: number | null
	cvr: number | null
	cpc: number | null
	break_even_acos: number | null
	economics_incomplete: boolean
	budget_utilisation: number | null
	days: number
}

export async function campaignPerformance(client: PoolClient, days = 30): Promise<CampaignRow[]> {
	return query<CampaignRow>(client, `
		with window_rows as (
			select * from ${mart("mart_ppc_campaign_daily")}
			 where is_settled and report_date >= current_date - ($1::int || ' days')::interval
		), latest_budget as (
			select distinct on (campaign_id) campaign_id, budget_amount, campaign_status, campaign_name, targeting_type
			  from window_rows order by campaign_id, report_date desc
		)
		select w.campaign_id, b.campaign_name, b.campaign_status, b.targeting_type, b.budget_amount,
			sum(w.impressions) as impressions, sum(w.clicks) as clicks, sum(w.cost) as cost,
			sum(w.attributed_orders_7d) as orders, sum(w.attributed_sales_7d) as sales,
			case when sum(w.attributed_sales_7d) > 0 then sum(w.cost) / sum(w.attributed_sales_7d) end as acos,
			case when sum(w.cost) > 0 then sum(w.attributed_sales_7d) / sum(w.cost) end as roas,
			case when sum(w.impressions) > 0 then sum(w.clicks)::numeric / sum(w.impressions) end as ctr,
			case when sum(w.clicks) > 0 then sum(w.attributed_orders_7d)::numeric / sum(w.clicks) end as cvr,
			case when sum(w.clicks) > 0 then sum(w.cost) / sum(w.clicks) end as cpc,
			min(w.break_even_acos) as break_even_acos, bool_or(w.economics_incomplete) as economics_incomplete,
			case when sum(w.budget_amount) > 0 then sum(w.cost) / sum(w.budget_amount) end as budget_utilisation,
			count(*) as days
		  from window_rows w join latest_budget b using (campaign_id)
		 group by w.campaign_id, b.campaign_name, b.campaign_status, b.targeting_type, b.budget_amount
		 order by sum(w.cost) desc`, [days])
}

export type AccountTotals = { cost: number; sales: number; orders: number; clicks: number; impressions: number; acos: number | null; campaigns: number; data_through: string | null }
export async function accountTotals(client: PoolClient, days = 30): Promise<AccountTotals | null> {
	const rows = await query<AccountTotals>(client, `select coalesce(sum(cost), 0) as cost, coalesce(sum(attributed_sales_7d), 0) as sales, coalesce(sum(attributed_orders_7d), 0) as orders, coalesce(sum(clicks), 0) as clicks, coalesce(sum(impressions), 0) as impressions, case when sum(attributed_sales_7d) > 0 then sum(cost) / sum(attributed_sales_7d) end as acos, count(distinct campaign_id) as campaigns, max(report_date)::text as data_through from ${mart("mart_ppc_campaign_daily")} where is_settled and report_date >= current_date - ($1::int || ' days')::interval`, [days])
	return rows[0] ?? null
}

export type PendingAction = { id: string; entity_type: string; entity_id: string; action_type: string; before_value: unknown; after_value: unknown; reason_text: string | null; clamped: boolean; clamp_note: string | null; requested_at: string; expires_at: string; rule_code: string | null; rule_name: string | null }
export async function pendingActions(client: PoolClient, limit = 100): Promise<PendingAction[]> {
	return query<PendingAction>(client, `select a.id, a.entity_type, a.entity_id, a.action_type, a.before_value, a.after_value, a.reason_text, a.clamped, a.clamp_note, a.requested_at, a.expires_at, r.code as rule_code, r.name as rule_name from action a left join rule r on r.id = a.rule_id where a.status = 'pending' and a.action_type <> 'flag' and a.expires_at > now() order by a.requested_at asc limit $1`, [limit])
}

export type Finding = { id: string; entity_type: string; entity_id: string; reason_text: string | null; requested_at: string; rule_code: string | null; rule_name: string | null }
export async function openFindings(client: PoolClient, limit = 100): Promise<Finding[]> {
	return query<Finding>(client, `select a.id, a.entity_type, a.entity_id, a.reason_text, a.requested_at, r.code as rule_code, r.name as rule_name from action a left join rule r on r.id = a.rule_id where a.status = 'pending' and a.action_type = 'flag' order by a.requested_at desc limit $1`, [limit])
}

export type Freshness = { dataset: string; last_success: string | null; last_status: string | null; hours_old: number | null }
export async function dataFreshness(client: PoolClient): Promise<Freshness[]> {
	return query<Freshness>(client, `select distinct on (dataset) dataset, finished_at::text as last_success, status as last_status, round(extract(epoch from (now() - finished_at)) / 3600.0, 1) as hours_old from pipeline_run order by dataset, started_at desc`)
}

export type AutomationState = { automation_enabled: boolean; dry_run: boolean; target_acos_default: number | null; max_changes_per_day: number | null; currency: string | null }
export async function automationState(client: PoolClient): Promise<AutomationState | null> {
	const rows = await query<AutomationState>(client, `select automation_enabled, dry_run, target_acos_default, max_changes_per_day, currency from tenant_settings limit 1`)
	return rows[0] ?? null
}

export type OpenAlert = { id: string; kind: string; severity: string; title: string; entity_ref: string | null; created_at: string; detail: unknown }
export async function openAlerts(client: PoolClient, limit = 20): Promise<OpenAlert[]> {
	return query<OpenAlert>(client, `select id::text, kind, severity, title, entity_ref, created_at::text, detail from alert where resolved_at is null order by case severity when 'critical' then 0 when 'warning' then 1 else 2 end, created_at desc limit $1`, [limit])
}

export type PipelineRunSummary = { dataset: string; status: string; started_at: string; finished_at: string | null; rows_loaded: number | null; error: string | null }
export async function recentPipelineRuns(client: PoolClient, limit = 20): Promise<PipelineRunSummary[]> {
	return query<PipelineRunSummary>(client, `select dataset, status, started_at::text, finished_at::text, rows_loaded, error from pipeline_run order by started_at desc limit $1`, [limit])
}
