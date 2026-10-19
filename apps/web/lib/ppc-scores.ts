import type { PoolClient } from "pg"
import { query, type TenantRole } from "./db"

export type PpcScore = { id:string; score_type:"health"|"opportunity"; scope_type:string; scope_id:string; score:number|null; coverage:number; components:Array<{key:string;weight:string;value:string|null;available:boolean;explanation:string}>; data_through:string|null; calculated_at:string; formula_version:number; formula_explanation:string }
export class ScoreInputError extends Error { constructor(message:string, readonly status=400){super(message)} }

export async function latestScores(client:PoolClient, tenantId:string, scopeType="account", scopeId=tenantId) {
	return query<PpcScore>(client,`select distinct on(s.score_type,s.scope_type,s.scope_id) s.id::text,s.score_type,s.scope_type,s.scope_id,s.score,s.coverage,s.components,s.data_through::text,s.calculated_at::text,f.version as formula_version,f.explanation as formula_explanation from ppc_score_snapshot s join ppc_score_formula_version f on f.id=s.formula_version_id and f.tenant_id=s.tenant_id where s.tenant_id=$1 and s.scope_type=$2 and s.scope_id=$3 order by s.score_type,s.scope_type,s.scope_id,s.calculated_at desc,s.id desc`,[tenantId,scopeType,scopeId])
}

export async function createFormula(client:PoolClient, tenantId:string, userId:string, role:TenantRole, raw:Record<string,unknown>) {
	if(role!=="owner"&&role!=="admin")throw new ScoreInputError("owner_or_admin_required",403)
	const formulaType=String(raw.formulaType??""); if(!["health","opportunity"].includes(formulaType))throw new ScoreInputError("invalid formulaType")
	const explanation=String(raw.explanation??"").trim(); if(!explanation||explanation.length>500)throw new ScoreInputError("explanation is required")
	if(!raw.weights||typeof raw.weights!=="object"||Array.isArray(raw.weights))throw new ScoreInputError("weights must be an object")
	const weights=raw.weights as Record<string,unknown>, entries=Object.entries(weights); if(!entries.length)throw new ScoreInputError("at least one weight is required")
	if(entries.some(([key,value])=>!key.trim()||!Number.isFinite(Number(value))||Number(value)<=0))throw new ScoreInputError("weights must be positive numbers")
	const rows=await query<{id:string;version:number}>(client,`insert into ppc_score_formula_version(tenant_id,formula_type,version,weights,explanation,created_by) select $1,$2,coalesce(max(version),0)+1,$3::jsonb,$4,$5 from ppc_score_formula_version where tenant_id=$1 and formula_type=$2 returning id::text,version`,[tenantId,formulaType,JSON.stringify(weights),explanation,userId])
	await query(client,`insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'ppc_score.formula_created',$3,$4::jsonb)`,[tenantId,userId,`ppc_score_formula_version:${rows[0].id}`,JSON.stringify({formulaType,version:rows[0].version,weights,explanation})])
	return rows[0]
}
