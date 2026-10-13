import { createHash } from "node:crypto"
import type { PoolClient } from "pg"
import { query } from "./db"

const ALLOWED = new Set(["automation_enabled","dry_run","target_acos_default","max_change_pct","cooldown_days","max_changes_per_day","max_budget_increase_per_day","blast_radius_pct","min_bid","max_bid","max_daily_budget","max_data_age_hours","settlement_lag_days"])
export class RolloutInputError extends Error {}
export function parseProposed(raw: string): Record<string, boolean|number> {
	let value: unknown; try { value=JSON.parse(raw) } catch { throw new RolloutInputError("Proposed values must be valid JSON.") }
	if(!value||Array.isArray(value)||typeof value!=="object") throw new RolloutInputError("Proposed values must be a JSON object.")
	const result: Record<string,boolean|number>={}
	for(const [key,item] of Object.entries(value)){if(!ALLOWED.has(key)||!(typeof item==="number"||typeof item==="boolean")||typeof item==="number"&&!Number.isFinite(item)) throw new RolloutInputError(`Unsupported value for ${key}.`);result[key]=item}
	if(!Object.keys(result).length) throw new RolloutInputError("At least one proposed value is required.")
	return result
}
export function deterministicCanary(ids:string[],fingerprint:string,pct:number){if(!(pct>0&&pct<=100))throw new RolloutInputError("Canary percent must be above 0 and at most 100.");const count=ids.length?Math.ceil(ids.length*pct/100):0;return [...ids].sort((a,b)=>createHash("sha256").update(`${fingerprint}:${a}`).digest("hex").localeCompare(createHash("sha256").update(`${fingerprint}:${b}`).digest("hex"))).slice(0,count)}

export async function createSimulation(client:PoolClient,tenantId:string,userId:string,proposed:Record<string,boolean|number>,exposureLimit:number){
	if(!Number.isInteger(exposureLimit)||exposureLimit<0)throw new RolloutInputError("Exposure limit must be a non-negative integer.")
	const currentRows=await query<{values:Record<string,unknown>}>(client,`select values from configuration_override_version where scope_type='tenant' and scope_id=$1 order by version desc limit 1`,[tenantId]);const before=currentRows[0]?.values??{}
	const candidates=await query<{entity_type:string;entity_id:string;spend:number;protected:boolean}>(client,`with latest as(select distinct on(entity_type,entity_id) entity_type,entity_id,metrics_snapshot from rule_evaluation where matched order by entity_type,entity_id,evaluated_at desc), controls as(select c.entity_type,c.entity_id,(select state from entity_automation_control_event where tenant_id=c.tenant_id and control_id=c.id order by occurred_at desc,id desc limit 1) state from entity_automation_control c), protections as(select entity_type,entity_value from entity_protection p where coalesce((select event_type from entity_protection_event where tenant_id=p.tenant_id and protection_id=p.id order by occurred_at desc,id desc limit 1),'created')='created') select l.entity_type,l.entity_id,coalesce((l.metrics_snapshot->>'cost')::numeric,0)::float8 spend,(coalesce(c.state,'AUTOMATED')<>'AUTOMATED' or p.entity_value is not null) protected from latest l left join controls c on c.entity_type=l.entity_type and lower(c.entity_id)=lower(l.entity_id) left join protections p on p.entity_type=l.entity_type and lower(p.entity_value)=lower(l.entity_id) order by l.entity_type,l.entity_id`)
	const changed=Object.entries(proposed).some(([k,v])=>before[k]!==v),affected=changed?candidates.filter(r=>!r.protected):[],excluded=candidates.filter(r=>r.protected),spend=affected.reduce((n,r)=>n+r.spend,0)
	if(affected.length>exposureLimit)throw new RolloutInputError(`Aggregate exposure ${affected.length} exceeds limit ${exposureLimit}.`)
	const input={before,proposed,candidates:candidates.map(r=>[r.entity_type,r.entity_id,r.spend,r.protected])},fingerprint=createHash("sha256").update(JSON.stringify(input)).digest("hex"),ids=affected.map(r=>`${r.entity_type}:${r.entity_id}`)
	const result={before,proposed,affectedIds:ids,protectedIds:excluded.map(r=>`${r.entity_type}:${r.entity_id}`),note:"Directional exposure estimate from latest rule evidence; not a causal forecast."}
	const rows=await query<{id:string}>(client,`insert into configuration_simulation(tenant_id,scope_type,scope_id,proposed_values,input_fingerprint,entity_count,affected_count,protected_excluded,estimated_spend,estimated_spend_delta,risk_score,exposure_limit,result,created_by) values($1,'tenant',$1,$2::jsonb,$3,$4,$5,$6,$7,0,$8,$9,$10::jsonb,$11) on conflict(tenant_id,input_fingerprint) do update set input_fingerprint=excluded.input_fingerprint returning id`,[tenantId,JSON.stringify(proposed),fingerprint,candidates.length,affected.length,excluded.length,spend,spend?Math.min(1,affected.length/Math.max(1,candidates.length)):0,exposureLimit,JSON.stringify(result),userId]);return rows[0]
}
