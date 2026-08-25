import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { openAlerts, recentPipelineRuns } from "@/lib/queries"
import { actionHistory, historyTotals } from "@/lib/queries-drilldown"
import { parseDays } from "@/lib/range"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
	const url = new URL(request.url)
	const days = parseDays(url.searchParams.get("days") ?? undefined)
	const tenantId = currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		days,
		totals: await historyTotals(client, days),
		history: await actionHistory(client, days),
		alerts: await openAlerts(client),
		pipeline_runs: await recentPipelineRuns(client),
	}))
	return NextResponse.json(data)
}
