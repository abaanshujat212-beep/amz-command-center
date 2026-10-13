"use server"

import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"

const TYPES = new Set(["keyword", "target", "search_term", "asin", "campaign"])
const DURATIONS = new Set(["one_time", "temporary", "persistent"])
const STATES = new Set(["HUMAN_OVERRIDE", "LOCKED"])
const text = (form: FormData, key: string) => String(form.get(key) ?? "").trim()
function requireAdmin(role: string) { if (role !== "owner" && role !== "admin") throw new Error("Only owners and admins can manage automation control.") }

export async function takeControl(form: FormData) {
	const actor = await currentContext(); requireAdmin(actor.role)
	const entityType=text(form,"entityType"), entityId=text(form,"entityId"), productScope=text(form,"productScope")||"*"
	const duration=text(form,"duration"), state=text(form,"state"), reason=text(form,"reason")
	if (!TYPES.has(entityType)||!DURATIONS.has(duration)||!STATES.has(state)||!entityId||!reason) throw new Error("Entity, state, duration and reason are required.")
	const raw=text(form,"expiresAt"), expires=duration==="temporary"?new Date(raw):null
	if (duration==="temporary"&&(!raw||Number.isNaN(expires?.getTime()))) throw new Error("Temporary control requires a valid expiry.")
	await withTenant(actor.tenantId, async c => {
		const rows=await query<{id:string}>(c,`insert into entity_automation_control(tenant_id,entity_type,entity_id,product_scope,duration,expires_at,reason,created_by) values($1,$2,$3,$4,$5,$6,$7,$8) returning id`,[actor.tenantId,entityType,entityId,productScope,duration,expires?.toISOString()??null,reason,actor.userId])
		await query(c,`insert into entity_automation_control_event(tenant_id,control_id,state,reason,actor_user_id) values($1,$2,$3,$4,$5)`,[actor.tenantId,rows[0].id,state,reason,actor.userId])
		await query(c,`insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'automation_control.started',$3,$4::jsonb)`,[actor.tenantId,actor.userId,`${entityType}:${entityId}`,JSON.stringify({controlId:rows[0].id,state,duration,expires,reason})])
	})
	revalidatePath("/settings/automation-control")
}

export async function resumeAutomation(form: FormData) {
	const actor=await currentContext(); requireAdmin(actor.role); const id=text(form,"id"), reason=text(form,"reason")
	if(!id||!reason) throw new Error("Control and reason are required.")
	await withTenant(actor.tenantId, async c => {
		await query(c,`insert into entity_automation_control_event(tenant_id,control_id,state,reason,actor_user_id) values($1,$2,'AUTOMATED',$3,$4)`,[actor.tenantId,id,reason,actor.userId])
		await query(c,`insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'automation_control.resumed',$3,$4::jsonb)`,[actor.tenantId,actor.userId,`control:${id}`,JSON.stringify({reason})])
	})
	revalidatePath("/settings/automation-control")
}

export async function requestNegative(form: FormData) {
	const actor=await currentContext(); requireAdmin(actor.role)
	const id=text(form,"id"), actionType=text(form,"actionType"), reason=text(form,"reason")
	if(!id||!reason||!["add_negative_exact","add_negative_phrase"].includes(actionType)) throw new Error("Control, negative type and reason are required.")
	await withTenant(actor.tenantId, async c => {
		const controls=await query<{entity_type:string;entity_id:string;state:string}>(c,`select c.entity_type,c.entity_id,(select state from entity_automation_control_event where tenant_id=c.tenant_id and control_id=c.id order by occurred_at desc,id desc limit 1) state from entity_automation_control c where c.tenant_id=$1 and c.id=$2`,[actor.tenantId,id])
		if(!controls.length||controls[0].entity_type!=="search_term") throw new Error("Negative requests require a search-term control.")
		if(controls[0].state==="AUTOMATED") throw new Error("Take control before requesting a manual negative.")
		await query(c,`insert into action(tenant_id,entity_type,entity_id,action_type,after_value,reason_text,idempotency_key,control_id,request_origin) values($1,'search_term',$2,$3,$4::jsonb,$5,$6,$7,'human') on conflict(tenant_id,idempotency_key) do nothing`,[actor.tenantId,controls[0].entity_id,actionType,JSON.stringify({term:controls[0].entity_id}),reason,`human:${id}:${actionType}`,id])
		await query(c,`insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'manual_negative.requested',$3,$4::jsonb)`,[actor.tenantId,actor.userId,`search_term:${controls[0].entity_id}`,JSON.stringify({controlId:id,actionType,reason})])
	})
	revalidatePath("/settings/automation-control"); revalidatePath("/approvals")
}
