import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import {
	latestLifecycleRun,
	lifecycleRecommendations,
	parseLifecycleDecision,
	parseLifecycleType,
} from "@/lib/queries-lifecycle"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
	const url = new URL(request.url)
	const type = parseLifecycleType(url.searchParams.get("type"))
	const decision = parseLifecycleDecision(url.searchParams.get("decision"))
	const tenantId = await currentTenantId()
	const data = await withTenant(tenantId, async (client) => {
		const run = await latestLifecycleRun(client)
		return {
			run,
			recommendations: run ? await lifecycleRecommendations(client, run.run_id, type, decision) : [],
		}
	})
	return NextResponse.json(data)
}
