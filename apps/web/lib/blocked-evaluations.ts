import type { PoolClient } from "pg"
import { query } from "@/lib/db"
import { blockedEvaluationReason, blockedEvaluationType } from "@/lib/blocked-evaluation-labels"

export const BLOCKED_EVALUATION_LIMIT = 50

// Deliberately project nothing that could include advertiser input or upstream
// payloads: no raw entity ID, rule reason, metrics, proposed action or evidence.
export async function listBlockedEvaluations(client: PoolClient, tenantId: string) {
	const rows = await query<{id: string; evaluated_at: string; data_through: string; blocked_by: string; recommendation_type: string | null}>(client, `
		select e.id::text, e.evaluated_at::text, e.data_through::text, e.blocked_by, e.recommendation_type
		from rule_evaluation e
		where e.tenant_id=$1 and e.matched is true and nullif(btrim(e.blocked_by),'') is not null
		order by e.evaluated_at desc,e.id desc
		limit $2
	`, [tenantId, BLOCKED_EVALUATION_LIMIT])
	return rows.map(row => ({
		id: row.id,
		evaluatedAt: row.evaluated_at,
		dataThrough: row.data_through,
		reason: blockedEvaluationReason(row.blocked_by),
		type: blockedEvaluationType(row.recommendation_type),
	}))
}
