import type { PoolClient, QueryResultRow } from "pg"
import { query } from "@/lib/db"
import { actionCapability } from "@/lib/action-support"

const TYPES=new Set(["bid_adjustment","budget_adjustment","entity_state","negative_targeting","keyword_harvest","placement_adjustment","diagnostic"])
const STATUSES=new Set(["pending","approved","applied","verified","rejected","expired","failed","rolled_back"])
const RISKS=new Set(["low","medium","high","critical"])
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const DATE=/^\d{4}-\d{2}-\d{2}$/

export class RecommendationQueryError extends Error { constructor(message:string,readonly status=400){super(message)} }
export type RecommendationFilters={type?:string;status?:string;risk?:string;entityType?:string;entityId?:string;from?:string;to?:string;confidence?:number;minConfidence?:number;limit:number;offset:number}
export type RecommendationRow=QueryResultRow&{id:string;recommendation_type:string|null;confidence:number|null;risk:string|null;lookback_days:number|null;entity_type:string;entity_id:string;action_type:string;status:string;reason_text:string|null;before_value:unknown;after_value:unknown;clamped:boolean;clamp_note:string|null;requested_at:string;expires_at:string;objective_snapshot:unknown;strategy_snapshot:unknown;economic_effect:unknown;expected_behavior:unknown;blocked_by:string|null;optimizer_run_id:string|null}

function one(raw:string|null,set:Set<string>,name:string){if(!raw)return undefined;if(!set.has(raw))throw new RecommendationQueryError(`invalid ${name}`);return raw}
export function parseRecommendationFilters(params:URLSearchParams):RecommendationFilters{
	const limit=Math.min(100,Math.max(1,Number(params.get("limit")??50))); const offset=Math.max(0,Number(params.get("offset")??0))
	if(!Number.isInteger(limit)||!Number.isInteger(offset))throw new RecommendationQueryError("limit and offset must be integers")
	const from=params.get("from")??undefined,to=params.get("to")??undefined;if((from&&!DATE.test(from))||(to&&!DATE.test(to)))throw new RecommendationQueryError("dates must use YYYY-MM-DD")
	const exactConfidence=params.has("confidence")?Number(params.get("confidence")):undefined;const minConfidence=params.has("minConfidence")?Number(params.get("minConfidence")):undefined
	if([exactConfidence,minConfidence].some(value=>value!==undefined&&(!Number.isFinite(value)||value<0||value>1)))throw new RecommendationQueryError("confidence must be between 0 and 1")
	return{type:one(params.get("type"),TYPES,"type"),status:one(params.get("status"),STATUSES,"status"),risk:one(params.get("risk"),RISKS,"risk"),entityType:params.get("entityType")?.trim()||undefined,entityId:params.get("entityId")?.trim()||undefined,from,to,confidence:exactConfidence,minConfidence,limit,offset}
}

export async function listRecommendations(client:PoolClient,tenantId:string,f:RecommendationFilters){
	const values:unknown[]=[tenantId];const where=["a.tenant_id=$1"]
	const add=(sql:string,value:unknown)=>{values.push(value);where.push(sql.replace("?",`$${values.length}`))}
	if(f.type)add("a.recommendation_type=?",f.type);if(f.status)add("a.status=?",f.status);if(f.risk)add("a.risk=?",f.risk)
	if(f.entityType)add("a.entity_type=?",f.entityType);if(f.entityId)add("a.entity_id=?",f.entityId)
	if(f.from)add("a.requested_at>=?::date",f.from);if(f.to)add("a.requested_at<?::date+interval '1 day'",f.to);if(f.confidence!==undefined)add("a.confidence=?",f.confidence);if(f.minConfidence!==undefined)add("a.confidence>=?",f.minConfidence)
	values.push(f.limit,f.offset)
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
