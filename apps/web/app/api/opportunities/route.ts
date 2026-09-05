import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { productOpportunities } from "@/lib/queries"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
	const url = new URL(request.url)
	const minScore = Number(url.searchParams.get("minScore") ?? 0)
	const tenantId = await currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		opportunities: await productOpportunities(client, Number.isFinite(minScore) ? minScore : 0),
	}))
	return NextResponse.json(data)
}
