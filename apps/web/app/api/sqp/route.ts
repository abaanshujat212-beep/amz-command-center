import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { sqpOpportunities } from "@/lib/queries"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
	const url = new URL(request.url)
	const action = url.searchParams.get("action") ?? "all"
	const tenantId = await currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		sqp: await sqpOpportunities(client, action),
	}))
	return NextResponse.json(data)
}
