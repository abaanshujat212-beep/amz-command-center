import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { automationState, dataFreshness } from "@/lib/queries"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET() {
	const tenantId = currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		automation: await automationState(client),
		freshness: await dataFreshness(client),
	}))
	return NextResponse.json(data)
}
