import type { PoolClient } from "pg"
import type { DashboardDefinition, DashboardFilter } from "@/lib/dashboard-studio"
import { query } from "@/lib/db"
import { accountTotals, campaignPerformance, productAnalytics, recentPipelineRuns, sqpOpportunities } from "@/lib/queries"
import { searchTermPerformance } from "@/lib/queries-drilldown"

export type DecisionOverlay = { id: string; entity_type: string; entity_id: string; action_type: string; status: string; reason_text: string | null; requested_at: string }
export type WidgetData = Record<string, unknown>
export type StudioData = { days: number; widgets: Record<string, WidgetData>; decisions: DecisionOverlay[] }

function scalar(filters: DashboardFilter[], field: string): string | null {
	const filter = filters.find(item => item.field === field && item.operator === "eq")
	return typeof filter?.value === "string" && filter.value.trim() ? filter.value.trim() : null
}

function selectedDays(definition: DashboardDefinition, fallback: number) {
	const filter = (definition.globalFilters ?? []).find(item => item.field === "dateRange" && item.operator === "between")
	if (!Array.isArray(filter?.value) || typeof filter.value[0] !== "string") return fallback
	const match = /^P(7|14|30|60|90)D$/.exec(filter.value[0])
	return match ? Number(match[1]) : fallback
}

function applyRows(rows: Record<string, unknown>[], filters: DashboardFilter[]) {
	const campaign = scalar(filters, "campaignId")
	const asin = scalar(filters, "asin")
	const sku = scalar(filters, "sku")
	const status = scalar(filters, "status")
	return rows.filter(row => (!campaign || row.campaign_id === campaign) && (!asin || row.asin === asin) && (!sku || row.sku === sku) && (!status || row.status === status || row.campaign_status === status))
}

export async function loadStudioData(client: PoolClient, definition: DashboardDefinition, fallbackDays = 30): Promise<StudioData> {
	const days = selectedDays(definition, fallbackDays)
	const queries = new Set(definition.widgets.map(widget => widget.query))
	const output: Record<string, WidgetData> = {}
	for (const queryKey of queries) {
		const widgetFilters = definition.widgets.filter(widget => widget.query === queryKey).flatMap(widget => widget.filters ?? [])
		const filters = [...(definition.globalFilters ?? []), ...widgetFilters]
		if (queryKey === "dashboard.summary") output[queryKey] = { total: await accountTotals(client, days) }
		else if (queryKey === "campaign.performance") output[queryKey] = { rows: applyRows(await campaignPerformance(client, days), filters) }
		else if (queryKey === "search_terms.performance") output[queryKey] = { rows: applyRows(await searchTermPerformance(client, days, scalar(filters, "campaignId"), 50), filters) }
		else if (queryKey === "product.economics") output[queryKey] = { rows: applyRows(await productAnalytics(client, days, 50), filters) }
		else if (queryKey === "sqp.opportunities") output[queryKey] = { rows: applyRows(await sqpOpportunities(client, "all", 50), filters) }
		else if (queryKey === "pipeline.health") output[queryKey] = { rows: await recentPipelineRuns(client, 20) }
	}
	const decisions = await query<DecisionOverlay>(client, `select id::text,entity_type,entity_id,action_type,status,reason_text,requested_at::text from action order by requested_at desc limit 30`)
	return { days, widgets: output, decisions }
}
