import { NextResponse } from "next/server"
import { ApprovalDecisionError, decideAction } from "@/lib/approval-decision"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

type Params = { params: Promise<{ id: string }> }

export async function POST(request: Request, { params }: Params) {
	const actor = await currentContext()
	const { id } = await params
	const body = await request.json().catch(() => ({})) as { decision?: unknown }
	const decision = body.decision === "approved" || body.decision === "rejected" ? body.decision : null
	if (!decision) return NextResponse.json({ error: "decision must be approved or rejected" }, { status: 400 })
	try {
		await decideAction({ tenantId: actor.tenantId, userId: actor.userId, role: actor.role, actionId: id, decision })
		return NextResponse.json({ ok: true, id, decision })
	} catch (err) {
		if (err instanceof ApprovalDecisionError) return NextResponse.json({ error: err.message }, { status: err.status })
		throw err
	}
}
