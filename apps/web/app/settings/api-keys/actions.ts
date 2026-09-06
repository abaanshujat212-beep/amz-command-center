"use server"

import { createHash, randomBytes } from "node:crypto"
import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { mayManageTenant } from "@/lib/rbac"
import { currentContext } from "@/lib/session"

function text(form: FormData, key: string): string { return String(form.get(key) ?? "").trim() }
function hashKey(key: string): string { return createHash("sha256").update(key).digest("hex") }
function scopes(form: FormData): string[] { const requested = form.getAll("scope").map(String).filter(Boolean); return requested.length ? requested : ["read"] }

export async function createApiKey(form: FormData) {
	const actor = await currentContext()
	if (!mayManageTenant(actor.role)) throw new Error("Only owners and admins can create API keys.")
	const name = text(form, "name")
	if (name.length < 2 || name.length > 80) throw new Error("Key name must be 2–80 characters.")
	const token = `ak_live_${randomBytes(24).toString("base64url")}`
	const prefix = token.slice(0, 15)
	await withTenant(actor.tenantId, async c => {
		await query(c, "insert into tenant_api_key(tenant_id,name,key_prefix,key_hash,scopes,created_by) values($1,$2,$3,$4,$5,$6)", [actor.tenantId,name,prefix,hashKey(token),scopes(form),actor.userId])
		await query(c, "insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'api_key.created',$3,$4::jsonb)", [actor.tenantId,actor.userId,`api_key:${prefix}`,JSON.stringify({name,prefix,scopes:scopes(form)})])
	})
	revalidatePath("/settings/api-keys")
	return { token }
}

export async function revokeApiKey(form: FormData) {
	const actor = await currentContext()
	if (!mayManageTenant(actor.role)) throw new Error("Only owners and admins can revoke API keys.")
	const id = text(form, "id")
	await withTenant(actor.tenantId, async c => {
		const before = await query<{key_prefix:string;name:string}>(c, "select key_prefix,name from tenant_api_key where tenant_id=$1 and id=$2 and revoked_at is null", [actor.tenantId,id])
		if (!before.length) return
		await query(c, "update tenant_api_key set revoked_at=now() where tenant_id=$1 and id=$2", [actor.tenantId,id])
		await query(c, "insert into audit_log(tenant_id,actor_user_id,action,entity,before) values($1,$2,'api_key.revoked',$3,$4::jsonb)", [actor.tenantId,actor.userId,`api_key:${before[0].key_prefix}`,JSON.stringify(before[0])])
	})
	revalidatePath("/settings/api-keys")
}
