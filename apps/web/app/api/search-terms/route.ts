import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { searchTermPerformance } from "@/lib/queries-drilldown"
import { parseDays } from "@/lib/range"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
	const url = new URL(request.url)
	const days = parseDays(url.searchParams.get("days") ?? undefined)
	const campaignId = url.searchParams.get("campaignId")
	const tenantId = currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		days,
		searchTerms: await searchTermPerformance(client, days, campaignId),
	}))
	return NextResponse.json(data)
}
