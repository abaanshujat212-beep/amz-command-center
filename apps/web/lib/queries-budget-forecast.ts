import type { PoolClient } from "pg"
import { mart, query } from "./db"

export type MonthlyBudgetForecast = {
	month_start: string
	month_end: string
	settled_through: string
	reporting_timezone: string
	tenant_currency: string
	elapsed_days: number
	remaining_days: number
	covered_days: number
	missing_days: number
	coverage_ratio: number | null
	observed_spend: number
	observed_sales: number
	estimated_spend_to_date: number | null
	estimated_sales_to_date: number | null
	spend_forecast_base: number | null
	spend_forecast_low: number | null
	spend_forecast_high: number | null
	sales_forecast_base: number | null
	sales_forecast_low: number | null
	sales_forecast_high: number | null
	monthly_limit: number | null
	limit_currency: string | null
	limit_status: "NO_LIMIT_CONFIGURED" | "CURRENCY_MISMATCH" | "NO_DATA" | "PROJECTED_OVER_LIMIT" | "WITHIN_LIMIT"
	confidence_score: number
	confidence: "INSUFFICIENT_DATA" | "LOW" | "MEDIUM" | "HIGH"
	assumptions: string
}

export type DryRunSummary = {
	id: string
	created_at: string
	proposed_values: Record<string, unknown>
	entity_count: number
	affected_count: number
	protected_excluded: number
	estimated_spend: number
	estimated_spend_delta: number
	risk_score: number
	exposure_limit: number
	state: string | null
	exposure_pct: number | null
}

export async function monthlyBudgetForecast(client: PoolClient) {
	const rows = await query<MonthlyBudgetForecast>(client, `
		select month_start::text, month_end::text, settled_through::text,
			reporting_timezone, tenant_currency, elapsed_days, remaining_days,
			covered_days, missing_days, coverage_ratio, observed_spend, observed_sales,
			estimated_spend_to_date, estimated_sales_to_date,
			spend_forecast_base, spend_forecast_low, spend_forecast_high,
			sales_forecast_base, sales_forecast_low, sales_forecast_high,
			monthly_limit, limit_currency, limit_status, confidence_score, confidence, assumptions
		from ${mart("mart_ppc_monthly_budget_forecast")}
		limit 1`)
	return rows[0] ?? null
}

export async function recentDryRunSummaries(client: PoolClient, limit = 5) {
	return query<DryRunSummary>(client, `
		select s.id::text, s.created_at::text, s.proposed_values,
			s.entity_count, s.affected_count, s.protected_excluded,
			s.estimated_spend::float8, s.estimated_spend_delta::float8,
			s.risk_score::float8, s.exposure_limit,
			e.state, e.exposure_pct::float8
		from configuration_simulation s
		left join lateral (
			select state, exposure_pct
			from configuration_rollout_event
			where tenant_id = s.tenant_id and simulation_id = s.id
			order by occurred_at desc, id desc
			limit 1
		) e on true
		order by s.created_at desc
		limit $1`, [limit])
}
