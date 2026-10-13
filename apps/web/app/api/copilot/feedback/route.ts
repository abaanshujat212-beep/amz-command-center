import { NextResponse } from "next/server"
import { CopilotScopeRequired, DecisionTraceInputError, cleanComment, cleanId, createFeedbackProposal } from "@/lib/decision-trace"
import { withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"

export async function POST(request: Request) {
	const actor = await currentContext()
	try {
		const body = await request.json().catch(() => ({})) as { explanationId?: unknown; feedback?: unknown; comment?: unknown }
		const explanationId = cleanId(body.explanationId, "explanationId")
		const feedback = String(body.feedback ?? "")
		const comment = cleanComment(body.comment)
		return NextResponse.json(await withTenant(actor.tenantId, client => createFeedbackProposal(client, actor.tenantId, actor.userId, explanationId, feedback, comment)), { status: 201 })
	} catch (error) {
		if (error instanceof CopilotScopeRequired) return NextResponse.json({ error: error.message }, { status: 403 })
		if (error instanceof DecisionTraceInputError) return NextResponse.json({ error: error.message }, { status: 400 })
		throw error
	}
}
