import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { createResearchProject, ResearchInputError } from "@/lib/research"
import { currentContext } from "@/lib/session"

export async function POST(request: Request) {
	try {
		const actor = await currentContext(); const body = await request.json().catch(() => ({}))
		const project = await withTenant(actor.tenantId, c => createResearchProject(c, actor.tenantId, actor.userId, actor.role, body))
		return NextResponse.json({ project }, { status: 201 })
	} catch (error) {
		if (error instanceof ResearchInputError) return NextResponse.json({ error: error.message }, { status: error.status })
		throw error
	}
}
