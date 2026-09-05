"use server"

import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { mayManageTenant } from "@/lib/rbac"

function value(form: FormData, key: string) { return String(form.get(key) ?? "").trim() }

export async function updateClientSettings(form: FormData) {
	const actor = await currentContext()
	if (!mayManageTenant(actor.role)) throw new Error("Only tenant owners and admins can edit client settings.")
	const name = value(form, "name")
	const slug = value(form, "slug").toLowerCase()
	const timezone = value(form, "timezone")
	const targetAcos = Number(value(form, "targetAcos")) / 100
	const maxChanges = Number(value(form, "maxChanges"))
	if (name.length < 2 || name.length > 100) throw new Error("Client name must be 2–100 characters.")
	if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) throw new Error("Slug may contain lowercase letters, numbers and single hyphens.")
	if (!timezone || timezone.length > 80) throw new Error("A valid timezone is required.")
	if (!Number.isFinite(targetAcos) || targetAcos <= 0 || targetAcos > 2) throw new Error("Target ACOS must be between 0.01% and 200%.")
	if (!Number.isInteger(maxChanges) || maxChanges < 1 || maxChanges > 500) throw new Error("Daily change limit must be 1–500.")
	await withTenant(actor.tenantId, async c => {
		const before = await query(c, "select t.name,t.slug,s.timezone,s.target_acos_default,s.max_changes_per_day from tenant t join tenant_settings s on s.tenant_id=t.id where t.id=$1", [actor.tenantId])
		await query(c, "update tenant set name=$2,slug=$3 where id=$1", [actor.tenantId,name,slug])
		await query(c, "update tenant_settings set timezone=$2,target_acos_default=$3,max_changes_per_day=$4 where tenant_id=$1", [actor.tenantId,timezone,targetAcos,maxChanges])
		await query(c, "insert into audit_log(tenant_id,actor_user_id,action,entity,before,after) values($1,$2,'tenant.settings_updated',$3,$4::jsonb,$5::jsonb)", [actor.tenantId,actor.userId,`tenant:${actor.tenantId}`,JSON.stringify(before[0] ?? {}),JSON.stringify({name,slug,timezone,target_acos_default:targetAcos,max_changes_per_day:maxChanges})])
	})
	revalidatePath("/", "layout")
	revalidatePath("/settings/client")
}
