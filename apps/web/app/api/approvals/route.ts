import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { pendingActions } from "@/lib/queries"
import { canApprove, currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET() {
	const tenantId = await currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		canApprove: await canApprove(),
		actions: await pendingActions(client),
	}))
	return NextResponse.json(data)
}
