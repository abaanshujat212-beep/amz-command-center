import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { reportError } from "@/lib/report-api"
import { getReport } from "@/lib/reports"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"
type Params = { params: Promise<{ id: string }> }

export async function GET(_request: Request, { params }: Params) {
	try {
		const actor = await currentContext()
		const { id } = await params
		return NextResponse.json({ report: await withTenant(actor.tenantId, c => getReport(c, actor.tenantId, id)) })
	} catch (err) { const response = reportError(err); if (response) return response; throw err }
}
