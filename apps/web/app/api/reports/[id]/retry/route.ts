import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { reportError } from "@/lib/report-api"
import { retryReport } from "@/lib/reports"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"
type Params = { params: Promise<{ id: string }> }

export async function POST(_request: Request, { params }: Params) {
	try {
		const actor = await currentContext()
		const { id } = await params
		const report = await withTenant(actor.tenantId, c => retryReport(c, actor.tenantId, actor.userId, actor.role, id))
		return NextResponse.json({ report })
	} catch (err) { const response = reportError(err); if (response) return response; throw err }
}
