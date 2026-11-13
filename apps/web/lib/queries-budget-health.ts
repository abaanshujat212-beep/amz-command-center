import type { PoolClient } from "pg"
import { mart, query } from "./db"

export type BudgetHealthRow = {
	campaign_id: string
	campaign_name: string
	campaign_status: string | null
	report_date: string
	budget_amount: number | null
	spend: number
	budget_utilisation: number | null
	budget_status: "unknown" | "over_budget_delivery" | "capped" | "underspend" | "on_track"
	settled_days_7d: number
	capped_days_7d: number
	budget_utilisation_7d: number | null
	exhaustion_risk: "unknown" | "high" | "watch" | "insufficient_data" | "low"
	acos_7d: number | null
	break_even_acos_7d: number | null
	efficiency_signal: "unknown_economics" | "no_attributed_sales" | "profitable_dark" | "inefficient_consumer" | "profitable" | "inefficient"
}

export async function budgetHealth(client: PoolClient, days = 30, limit = 200): Promise<BudgetHealthRow[]> {
	return query<BudgetHealthRow>(client, `
		select distinct on (campaign_id)
			campaign_id, campaign_name, campaign_status, report_date::text, budget_amount,
			spend, budget_utilisation, budget_status, settled_days_7d, capped_days_7d,
			budget_utilisation_7d, exhaustion_risk, acos_7d, break_even_acos_7d, efficiency_signal
		from ${mart("mart_ppc_budget_health_daily")}
		where report_date >= current_date - ($1::int || ' days')::interval
		order by campaign_id, report_date desc
		limit $2`, [days, limit])
}
