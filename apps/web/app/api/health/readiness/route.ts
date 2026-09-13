import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { readinessSnapshot } from "@/lib/queries-readiness"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET() {
	const tenantId = await currentTenantId()
	return NextResponse.json(await withTenant(tenantId, readinessSnapshot))
}
