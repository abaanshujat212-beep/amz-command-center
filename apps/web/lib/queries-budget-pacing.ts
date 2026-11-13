import type { PoolClient } from "pg"
import { mart, query } from "./db"

export type BudgetPacingRow = {
	campaign_id: string
	campaign_name: string
	campaign_status: string | null
	report_date: string
	budget_amount: number | null
	spend: number
	budget_utilisation: number | null
	budget_status: string
	settled_days_7d: number
	capped_days_7d: number
	exhaustion_risk: string
	daily_target_spend: number | null
	observed_daily_pace: number | null
	pace_ratio: number | null
	pacing_status: "unknown" | "under_paced" | "on_pace" | "over_paced"
}

/**
 * Daily pacing compares the latest settled day's delivery with a linear share
 * of the campaign's daily budget. It is a diagnostic signal, not an intraday
 * pacing curve or an instruction to change budget.
 */
export async function budgetPacing(client: PoolClient, days = 30, limit = 200) {
	return query<BudgetPacingRow>(client, `
		with latest as (
			select distinct on (campaign_id)
				campaign_id, campaign_name, campaign_status, report_date::text,
				budget_amount, spend, budget_utilisation, budget_status,
				settled_days_7d, capped_days_7d, exhaustion_risk
			from ${mart("mart_ppc_budget_health_daily")}
			where report_date >= current_date - ($1::int || ' days')::interval
			order by campaign_id, report_date desc
		)
		select *,
			case when budget_amount > 0 then budget_amount / 24.0 end as daily_target_spend,
			case when settled_days_7d > 0 then spend / 24.0 end as observed_daily_pace,
			case when budget_amount > 0 and settled_days_7d > 0
				then spend / budget_amount end as pace_ratio,
			case
				when budget_amount is null or budget_amount <= 0 or settled_days_7d = 0 then 'unknown'
				when spend / budget_amount < 0.8 then 'under_paced'
				when spend / budget_amount > 1.2 then 'over_paced'
				else 'on_pace'
			end as pacing_status
		from latest
		order by
			case when budget_amount > 0 and settled_days_7d > 0 then 0 else 1 end,
			abs(coalesce(spend / nullif(budget_amount, 0), 1) - 1) desc,
			campaign_name
		limit $2`, [days, limit])
}
