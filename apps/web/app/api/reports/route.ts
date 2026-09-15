import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { reportError } from "@/lib/report-api"
import { createReport, listReports } from "@/lib/reports"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET() {
	try {
		const actor = await currentContext()
		return NextResponse.json({ reports: await withTenant(actor.tenantId, c => listReports(c, actor.tenantId)) })
	} catch (err) { const response = reportError(err); if (response) return response; throw err }
}

export async function POST(request: Request) {
	try {
		const actor = await currentContext()
		const body = await request.json().catch(() => ({}))
		const report = await withTenant(actor.tenantId, c => createReport(c, actor.tenantId, actor.userId, actor.role, body))
		return NextResponse.json({ report }, { status: 201 })
	} catch (err) { const response = reportError(err); if (response) return response; throw err }
}
