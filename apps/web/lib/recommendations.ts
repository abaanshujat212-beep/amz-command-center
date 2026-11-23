import type { PoolClient, QueryResultRow } from "pg"
import { query } from "@/lib/db"
import { actionCapability } from "@/lib/action-support"

import { RecommendationQueryError, type RecommendationFilters } from "@/lib/recommendation-filters"
export { RecommendationQueryError, parseRecommendationFilters } from "@/lib/recommendation-filters"

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export type RecommendationRow=QueryResultRow&{id:string;recommendation_type:string|null;confidence:number|null;risk:string|null;lookback_days:number|null;entity_type:string;entity_id:string;action_type:string;status:string;reason_text:string|null;before_value:unknown;after_value:unknown;clamped:boolean;clamp_note:string|null;requested_at:string;expires_at:string;objective_snapshot:unknown;strategy_snapshot:unknown;economic_effect:unknown;expected_behavior:unknown;blocked_by:string|null;optimizer_run_id:string|null}

export async function listRecommendations(client:PoolClient,tenantId:string,f:RecommendationFilters,lookAhead=false){
	const values:unknown[]=[tenantId];const where=["a.tenant_id=$1"]
	const add=(sql:string,value:unknown)=>{values.push(value);where.push(sql.replace("?",`$${values.length}`))}
	if(f.type)add("a.recommendation_type=?",f.type);if(f.status)add("a.status=?",f.status);if(f.risk)add("a.risk=?",f.risk)
	if(f.entityType)add("a.entity_type=?",f.entityType);if(f.entityId)add("a.entity_id=?",f.entityId)
	if(f.from)add("a.requested_at>=(?::date::timestamp at time zone 'UTC')",f.from);if(f.to)add("a.requested_at<((?::date+1)::timestamp at time zone 'UTC')",f.to);if(f.confidence!==undefined)add("a.confidence=?",f.confidence);if(f.minConfidence!==undefined)add("a.confidence>=?",f.minConfidence)
	values.push(f.limit+(lookAhead?1:0),f.offset)
	return query<RecommendationRow>(client,`select a.id::text,a.recommendation_type,a.confidence::float8,a.risk,a.lookback_days,a.entity_type,a.entity_id,a.action_type,a.status,a.reason_text,a.before_value,a.after_value,a.clamped,a.clamp_note,a.requested_at::text,a.expires_at::text,a.objective_snapshot,a.strategy_snapshot,a.economic_effect,a.expected_behavior,e.blocked_by,e.run_id::text optimizer_run_id from action a left join rule_evaluation e on e.tenant_id=a.tenant_id and e.id=a.evaluation_id where ${where.join(" and ")} order by a.requested_at desc,a.id desc limit $${values.length-1} offset $${values.length}`,values)
}

function safeSourceRef(value:string){return /(?:token|secret|api[_-]?key|password|authorization)/i.test(value)||value.includes("?")?"[redacted]":value}
export async function recommendationDetail(client:PoolClient,tenantId:string,id:string){
	if(!UUID.test(id))throw new RecommendationQueryError("invalid recommendation id")
	const rows=await query<RecommendationRow>(client,`select a.id::text,a.recommendation_type,a.confidence::float8,a.risk,a.lookback_days,a.entity_type,a.entity_id,a.action_type,a.status,a.reason_text,a.before_value,a.after_value,a.clamped,a.clamp_note,a.requested_at::text,a.expires_at::text,a.objective_snapshot,a.strategy_snapshot,a.economic_effect,a.expected_behavior,e.blocked_by,e.run_id::text optimizer_run_id from action a left join rule_evaluation e on e.tenant_id=a.tenant_id and e.id=a.evaluation_id where a.tenant_id=$1 and a.id=$2`,[tenantId,id])
	if(!rows[0])throw new RecommendationQueryError("recommendation not found",404)
	const evidence=await query<{evidence_kind:string;source_type:string;source_ref:string;observed_at:string;data_through:string|null;completeness:string;metric_keys:string[];detail:unknown}>(client,"select evidence_kind,source_type,source_ref,observed_at::text,data_through::text,completeness,metric_keys,detail from recommendation_evidence where tenant_id=$1 and action_id=$2 order by created_at,id",[tenantId,id])
	return{...rows[0],capability:actionCapability(rows[0].entity_type,rows[0].action_type),dependencyState:{blockedBy:rows[0].blocked_by},evidence:evidence.map(item=>({...item,source_ref:safeSourceRef(item.source_ref)}))}
}
