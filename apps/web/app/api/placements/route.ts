import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { placementPerformance } from "@/lib/queries-feature-surfaces"
import { parseDays } from "@/lib/range"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
	const url = new URL(request.url)
	const days = parseDays(url.searchParams.get("days") ?? undefined)
	const tenantId = await currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		days,
		placements: await placementPerformance(client, days),
	}))
	return NextResponse.json(data)
}
