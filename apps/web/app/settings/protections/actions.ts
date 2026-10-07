"use server"

import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"

const TYPES = new Set(["keyword", "search_term", "asin"])
const POLICIES = new Set(["allow", "deny", "protect"])
const DURATIONS = new Set(["one_time", "temporary", "persistent"])
function text(form: FormData, key: string) { return String(form.get(key) ?? "").trim() }
function requireAdmin(role: string) { if (role !== "owner" && role !== "admin") throw new Error("Only owners and admins can manage protections.") }

export async function createProtection(form: FormData) {
	const actor = await currentContext(); requireAdmin(actor.role)
	const entityType = text(form, "entityType"), entityValue = text(form, "entityValue"), productScope = text(form, "productScope") || "*"
	const policy = text(form, "policy"), duration = text(form, "duration"), reason = text(form, "reason")
	if (!TYPES.has(entityType) || !POLICIES.has(policy) || !DURATIONS.has(duration)) throw new Error("Invalid protection type, policy or duration.")
	if (!entityValue || !reason) throw new Error("Entity value and reason are required.")
	const expiresRaw = text(form, "expiresAt")
	const expiresAt = duration === "temporary" ? new Date(expiresRaw) : null
	if (duration === "temporary" && (!expiresRaw || Number.isNaN(expiresAt?.getTime()))) throw new Error("Temporary protection requires a valid expiry.")
	await withTenant(actor.tenantId, async c => {
		await query(c, `insert into entity_protection(tenant_id,entity_type,entity_value,product_scope,policy,duration,expires_at,reason,created_by) values($1,$2,$3,$4,$5,$6,$7,$8,$9)`, [actor.tenantId,entityType,entityValue,productScope,policy,duration,expiresAt?.toISOString() ?? null,reason,actor.userId])
		await query(c, `insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'entity_protection.created',$3,$4::jsonb)`, [actor.tenantId,actor.userId,`${entityType}:${entityValue}`,JSON.stringify({productScope,policy,duration,expiresAt,reason})])
	})
	revalidatePath("/settings/protections")
}

export async function releaseProtection(form: FormData) {
	const actor = await currentContext(); requireAdmin(actor.role)
	const id = text(form, "id"), reason = text(form, "reason")
	if (!id || !reason) throw new Error("Protection and release reason are required.")
	await withTenant(actor.tenantId, async c => {
		const rows = await query<{id:string}>(c, "select id from entity_protection where tenant_id=$1 and id=$2", [actor.tenantId,id])
		if (!rows.length) throw new Error("Protection not found.")
		await query(c, `insert into entity_protection_event(tenant_id,protection_id,event_type,reason,actor_user_id) values($1,$2,'released',$3,$4)`, [actor.tenantId,id,reason,actor.userId])
		await query(c, `insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'entity_protection.released',$3,$4::jsonb)`, [actor.tenantId,actor.userId,`protection:${id}`,JSON.stringify({reason})])
	})
	revalidatePath("/settings/protections")
}
