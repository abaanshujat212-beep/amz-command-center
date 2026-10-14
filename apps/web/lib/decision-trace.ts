import type { PoolClient } from "pg"
import { query } from "@/lib/db"

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const FEEDBACK = new Set(["helpful", "not_helpful", "request_review"])

export class DecisionTraceInputError extends Error {}
export class CopilotScopeRequired extends Error {}

export type TraceEvidence = {
	id: string
	kind: "rule_evaluation" | "action" | "execution_event"
	event: string
	at: string
	detail: Record<string, unknown>
}

type ActionEvidence = {
	id: string; entity_type: string; entity_id: string; action_type: string; status: string
	requested_at: string; reason_text: string | null; before_value: unknown; after_value: unknown
	evaluation_id: string | null; data_through: string | null; evaluated_at: string | null
	metrics_snapshot: Record<string, unknown> | null; proposed_action: unknown; blocked_by: string | null
}

export function cleanId(value: unknown, label: string): string {
	const text = String(value ?? "").trim()
	if (!UUID.test(text)) throw new DecisionTraceInputError(`${label} must be a UUID.`)
	return text
}

export function cleanComment(value: unknown): string | null {
	const text = String(value ?? "").trim()
	if (!text) return null
	if (text.length > 2000) throw new DecisionTraceInputError("Feedback is limited to 2,000 characters.")
	return text
}

export async function requireCopilotScope(client: PoolClient, tenantId: string, userId: string) {
	const rows = await query<{ role: string; access_scopes: string[] }>(client,
		"select role,access_scopes from tenant_member where tenant_id=$1 and user_id=$2", [tenantId, userId])
	const privileged = rows[0]?.role === "owner" || rows[0]?.role === "admin"
	if (!rows.length || (!privileged && !rows[0].access_scopes.includes("copilot"))) {
		throw new CopilotScopeRequired("Copilot access is not assigned to this member.")
	}
}

export async function explainAction(client: PoolClient, tenantId: string, userId: string, actionId: string) {
	await requireCopilotScope(client, tenantId, userId)
	const actions = await query<ActionEvidence>(client, `select a.id::text,a.entity_type,a.entity_id,a.action_type,a.status,
		a.requested_at::text,a.reason_text,a.before_value,a.after_value,a.evaluation_id::text,
		r.data_through::text,r.evaluated_at::text,r.metrics_snapshot,r.proposed_action,r.blocked_by
		from action a left join rule_evaluation r on r.tenant_id=a.tenant_id and r.id=a.evaluation_id
		where a.tenant_id=$1 and a.id=$2`, [tenantId, actionId])
	if (!actions.length) throw new DecisionTraceInputError("Decision was not found in this tenant.")
	const action = actions[0]
	const events = await query<{ id: string; event_type: string; occurred_at: string; previous_state: string | null; new_state: string | null; provider_result_classification: string | null; metadata: Record<string, unknown> }>(client,
		`select id::text,event_type,occurred_at::text,previous_state,new_state,provider_result_classification,metadata
		 from action_execution_event where tenant_id=$1 and action_id=$2 order by occurred_at,id`, [tenantId, actionId])
	const evidence: TraceEvidence[] = []
	if (action.evaluation_id) evidence.push({ id: action.evaluation_id, kind: "rule_evaluation", event: action.blocked_by ? "rule.blocked" : "rule.evaluated", at: action.evaluated_at ?? action.requested_at, detail: { dataThrough: action.data_through, metrics: action.metrics_snapshot, proposedAction: action.proposed_action, blockedBy: action.blocked_by } })
	evidence.push({ id: action.id, kind: "action", event: `action.${action.status}`, at: action.requested_at, detail: { entityType: action.entity_type, entityId: action.entity_id, actionType: action.action_type, beforeValue: action.before_value, afterValue: action.after_value, reason: action.reason_text } })
	for (const event of events) evidence.push({ id: event.id, kind: "execution_event", event: event.event_type, at: event.occurred_at, detail: { previousState: event.previous_state, newState: event.new_state, result: event.provider_result_classification, metadata: event.metadata } })
	const narrative = `${action.action_type} for ${action.entity_type} ${action.entity_id} is ${action.status}. ${action.reason_text ?? "No stored rule reason was recorded."} This trace contains ${evidence.length} immutable stored event${evidence.length === 1 ? "" : "s"}; it does not infer an unstored cause.`
	const context = { screen: "copilot", entityType: action.entity_type, entityId: action.entity_id, actionId: action.id }
	const inserted = await query<{ id: string; created_at: string }>(client,
		`insert into copilot_decision_explanation(tenant_id,action_id,actor_user_id,context,narrative,evidence)
		 values($1,$2,$3,$4::jsonb,$5,$6::jsonb) returning id::text,created_at::text`,
		[tenantId, action.id, userId, JSON.stringify(context), narrative, JSON.stringify(evidence)])
	return { id: inserted[0].id, createdAt: inserted[0].created_at, narrative, context, evidence, noWrite: true }
}

export async function createFeedbackProposal(client: PoolClient, tenantId: string, userId: string, explanationId: string, feedback: string, comment: string | null) {
	await requireCopilotScope(client, tenantId, userId)
	if (!FEEDBACK.has(feedback)) throw new DecisionTraceInputError("Unknown feedback type.")
	if (feedback === "request_review" && !comment) throw new DecisionTraceInputError("A review request needs a comment.")
	const rows = await query<{ id: string; status: string }>(client,
		`insert into copilot_feedback_proposal(tenant_id,explanation_id,actor_user_id,feedback,comment)
		 select $1,$2,$3,$4,$5 from copilot_decision_explanation where tenant_id=$1 and id=$2
		 returning id::text,status`, [tenantId, explanationId, userId, feedback, comment])
	if (!rows.length) throw new DecisionTraceInputError("Explanation was not found in this tenant.")
	await query(client, `insert into audit_log(tenant_id,actor_user_id,action,entity,after)
		values($1,$2,'copilot.feedback_proposed',$3,$4::jsonb)`, [tenantId, userId, `explanation:${explanationId}`, JSON.stringify({ proposalId: rows[0].id, feedback, status: rows[0].status })])
	return { ...rows[0], appliesAutomatically: false }
}
