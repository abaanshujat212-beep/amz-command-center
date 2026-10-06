import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { createResearchCandidate, listResearchCandidates, ResearchInputError } from "@/lib/research"
import { currentContext } from "@/lib/session"

export async function GET() {
	const actor = await currentContext()
	return NextResponse.json({ candidates: await withTenant(actor.tenantId, c => listResearchCandidates(c, actor.tenantId)) })
}

export async function POST(request: Request) {
	try {
		const actor = await currentContext(); const body = await request.json().catch(() => ({}))
		const candidate = await withTenant(actor.tenantId, c => createResearchCandidate(c, actor.tenantId, actor.userId, actor.role, body))
		return NextResponse.json({ candidate }, { status: 201 })
	} catch (error) {
		if (error instanceof ResearchInputError) return NextResponse.json({ error: error.message }, { status: error.status })
		throw error
	}
}
