import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { ResearchInputError, setResearchDisposition } from "@/lib/research"
import { currentContext } from "@/lib/session"

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
	try {
		const actor = await currentContext(); const { id } = await context.params; const body = await request.json().catch(() => ({}))
		const candidate = await withTenant(actor.tenantId, c => setResearchDisposition(c, actor.tenantId, actor.role, id, body.status))
		return NextResponse.json({ candidate })
	} catch (error) {
		if (error instanceof ResearchInputError) return NextResponse.json({ error: error.message }, { status: error.status })
		throw error
	}
}
