import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { verificationScorecards } from "@/lib/queries-verification"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET() {
	const tenantId = await currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		verification: await verificationScorecards(client),
	}))
	return NextResponse.json(data)
}
