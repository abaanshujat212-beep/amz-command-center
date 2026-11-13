import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { budgetPacing } from "@/lib/queries-budget-pacing"

export const dynamic = "force-dynamic"

export async function GET() {
	const actor = await currentContext()
	const rows = await withTenant(actor.tenantId, client => budgetPacing(client))
	return NextResponse.json({ rows, mode: "daily_settled_diagnostic" })
}
