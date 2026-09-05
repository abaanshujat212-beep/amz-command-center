import type { PoolClient } from "pg"
import { query } from "./db"

export type VerificationScorecard = { id:string; entity_type:string; entity_id:string; action_type:string; status:string; outcome:string|null; applied_at:string|null; verified_at:string|null; before_value:unknown; after_value:unknown; impact_jsonb:unknown; reason_text:string|null; rule_code:string|null; rule_name:string|null }
export async function verificationScorecards(client: PoolClient, limit = 100): Promise<VerificationScorecard[]> { return query<VerificationScorecard>(client, `select a.id::text,a.entity_type,a.entity_id,a.action_type,a.status,a.outcome,a.applied_at::text,a.verified_at::text,a.before_value,a.after_value,a.impact_jsonb,a.reason_text,r.code as rule_code,r.name as rule_name from action a left join rule r on r.id=a.rule_id where a.status in ('applied','verified') and a.action_type <> 'flag' order by coalesce(a.verified_at,a.applied_at,a.requested_at) desc limit $1`, [limit]) }
