import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { skuEconomics } from "@/lib/queries"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET() {
	const tenantId = await currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		economics: await skuEconomics(client),
	}))
	return NextResponse.json(data)
}
