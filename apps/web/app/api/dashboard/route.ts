import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { accountTotals, campaignPerformance, openFindings } from "@/lib/queries"
import { parseDays } from "@/lib/range"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
	const url = new URL(request.url)
	const days = parseDays(url.searchParams.get("days") ?? undefined)
	const tenantId = currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		days,
		totals: await accountTotals(client, days),
		campaigns: await campaignPerformance(client, days),
		findings: await openFindings(client, 20),
	}))
	return NextResponse.json(data)
}
