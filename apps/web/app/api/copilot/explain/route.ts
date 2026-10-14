import { NextResponse } from "next/server"
import { CopilotScopeRequired, DecisionTraceInputError, cleanId, explainAction } from "@/lib/decision-trace"
import { withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function POST(request: Request) {
	const actor = await currentContext()
	try {
		const body = await request.json().catch(() => ({})) as { actionId?: unknown }
		const actionId = cleanId(body.actionId, "actionId")
		return NextResponse.json(await withTenant(actor.tenantId, client => explainAction(client, actor.tenantId, actor.userId, actionId)))
	} catch (error) {
		if (error instanceof CopilotScopeRequired) return NextResponse.json({ error: error.message }, { status: 403 })
		if (error instanceof DecisionTraceInputError) return NextResponse.json({ error: error.message }, { status: 400 })
		throw error
	}
}
