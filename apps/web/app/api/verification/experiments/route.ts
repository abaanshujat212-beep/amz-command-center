import { NextResponse } from "next/server"
import { addExperimentOutcome, createActionExperiment, ExperimentInputError, listActionExperiments } from "@/lib/action-experiments"
import { withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET() {
	const actor = await currentContext()
	return NextResponse.json({ experiments: await withTenant(actor.tenantId, client => listActionExperiments(client, actor.tenantId)) })
}

export async function POST(request: Request) {
	try {
		const actor = await currentContext(), body = await request.json().catch(() => ({}))
		if (body && typeof body === "object" && !Array.isArray(body) && "experimentId" in body) {
			const outcome = await withTenant(actor.tenantId, client => addExperimentOutcome(client, actor.tenantId, actor.userId, actor.role, body))
			return NextResponse.json({ outcome }, { status: 201 })
		}
		const experiment = await withTenant(actor.tenantId, client => createActionExperiment(client, actor.tenantId, actor.userId, actor.role, body))
		return NextResponse.json({ experiment }, { status: 201 })
	} catch (error) {
		if (error instanceof ExperimentInputError) return NextResponse.json({ error: error.message }, { status: error.status })
		throw error
	}
}

export async function PATCH(request: Request) {
	try {
		const actor = await currentContext()
		if (actor.role !== "owner" && actor.role !== "admin") return NextResponse.json({ error: "owner_or_admin_required" }, { status: 403 })
		const body = await request.json().catch(() => ({})), id = typeof body?.id === "string" ? body.id : "", status = body?.status
		if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).some(key => !["id","status","summary"].includes(key))) throw new ExperimentInputError("Unsupported experiment update fields.")
		if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id) || !["running","completed","cancelled"].includes(status)) throw new ExperimentInputError("A valid experiment ID and next status are required.")
		let summary: string | null = null
		if (body.summary !== undefined && body.summary !== null) {
			if (typeof body.summary !== "string" || body.summary.trim().length > 4000) throw new ExperimentInputError("summary must be at most 4000 characters.")
			summary = body.summary.trim()
		}
		const result = await withTenant(actor.tenantId, async client => {
			const allowedFrom = status === "running" ? ["planned"] : status === "completed" ? ["running"] : ["planned","running"]
			const row = (await client.query("update action_experiment set status=$3,end_date=case when $3='completed' then current_date when $3='cancelled' then greatest(current_date,start_date) else null end,summary=coalesce($4,summary),updated_at=now() where tenant_id=$1 and id=$2::uuid and status=any($5::text[]) and ($3<>'completed' or start_date<=current_date) returning id::text,status,end_date::text,summary",[actor.tenantId,id,status,summary,allowedFrom])).rows[0]
			if (!row) throw new ExperimentInputError("Experiment not found, already terminal, or not started yet.",404)
			await client.query("insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,$3,$4,$5::jsonb)",[actor.tenantId,actor.userId,`action_experiment.${status}`,`action_experiment:${id}`,JSON.stringify(row)])
			return row
		})
		return NextResponse.json({ experiment: result })
	} catch (error) {
		if (error instanceof ExperimentInputError) return NextResponse.json({ error: error.message }, { status: error.status })
		throw error
	}
}
