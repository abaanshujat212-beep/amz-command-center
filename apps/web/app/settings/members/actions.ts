"use server"

import { randomUUID } from "node:crypto"
import { hashPassword } from "better-auth/crypto"
import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { ACCESS_SCOPES, defaultScopes, mayAssignRole, mayManageMembers, type AccessScope, type AssignableRole } from "@/lib/rbac"

function text(form: FormData, key: string) { return String(form.get(key) ?? "").trim() }
function role(form: FormData): AssignableRole { const value = text(form, "role"); if (value !== "admin" && value !== "user" && value !== "analyst" && value !== "viewer") throw new Error("Role must be admin, user, analyst or viewer."); return value }
function scopes(form: FormData, assignedRole: string): AccessScope[] { const selected = form.getAll("scope").map(String).filter((s): s is AccessScope => (ACCESS_SCOPES as readonly string[]).includes(s)); return selected.length ? selected : defaultScopes(assignedRole) }

export async function addMember(form: FormData) {
	const actor = await currentContext()
	if (!mayManageMembers(actor.role)) throw new Error("Only owners and admins can manage members.")
	const assignedRole = role(form), assignedScopes = scopes(form, assignedRole)
	if (!mayAssignRole(actor.role, assignedRole)) throw new Error("You cannot assign that role.")
	const email = text(form, "email").toLowerCase(), name = text(form, "name"), password = text(form, "password")
	if (!/^\S+@\S+\.\S+$/.test(email) || !name) throw new Error("Name and a valid email are required.")
	if (password.length < 12) throw new Error("Temporary password must be at least 12 characters.")
	const passwordHash = await hashPassword(password)
	await withTenant(actor.tenantId, async c => {
		let users = await query<{ id: string }>(c, "select id from auth.auth_user where lower(email) = $1", [email])
		if (users.length === 0) { const id = randomUUID(); users = await query(c, "insert into auth.auth_user (id,name,email,email_verified) values ($1,$2,$3,false) returning id", [id,name,email]); await query(c, "insert into auth.auth_account (id,issuer,account_id,provider_id,user_id,password,updated_at) values ($1,'local:credential',$2,'credential',$3,$4,now())", [randomUUID(),id,id,passwordHash]) }
		await query(c, "insert into tenant_member (tenant_id,user_id,role,access_scopes) values ($1,$2,$3,$4)", [actor.tenantId,users[0].id,assignedRole,assignedScopes])
		await query(c, "insert into audit_log (tenant_id,actor_user_id,action,entity,after) values ($1,$2,'member.added',$3,$4::jsonb)", [actor.tenantId,actor.userId,`user:${users[0].id}`,JSON.stringify({email,role:assignedRole,scopes:assignedScopes})])
	})
	revalidatePath("/settings/members")
}

export async function updateMemberRole(form: FormData) {
	const actor = await currentContext(), assignedRole = role(form), userId = text(form, "userId"), assignedScopes = scopes(form, assignedRole)
	if (!mayAssignRole(actor.role, assignedRole)) throw new Error("You cannot assign that role.")
	await withTenant(actor.tenantId, async c => {
		const before = await query<{ role: string; access_scopes: string[] }>(c, "select role,access_scopes from tenant_member where tenant_id=$1 and user_id=$2", [actor.tenantId,userId])
		if (!before.length || before[0].role === "owner") throw new Error("The tenant owner role cannot be changed here.")
		if (actor.role === "admin" && before[0].role === "admin") throw new Error("Admins cannot manage other admins.")
		await query(c, "update tenant_member set role=$3, access_scopes=$4 where tenant_id=$1 and user_id=$2", [actor.tenantId,userId,assignedRole,assignedScopes])
		await query(c, "insert into audit_log (tenant_id,actor_user_id,action,entity,before,after) values ($1,$2,'member.access_changed',$3,$4::jsonb,$5::jsonb)", [actor.tenantId,actor.userId,`user:${userId}`,JSON.stringify(before[0]),JSON.stringify({role:assignedRole,access_scopes:assignedScopes})])
	})
	revalidatePath("/settings/members")
}

export async function createRoleTemplate(form: FormData) {
	const actor = await currentContext()
	if (actor.role !== "owner") throw new Error("Only the owner can create custom role templates.")
	const name = text(form, "name"), description = text(form, "description"), assignedScopes = scopes(form, "viewer")
	if (name.length < 2 || name.length > 60) throw new Error("Role template name must be 2–60 characters.")
	await withTenant(actor.tenantId, async c => {
		await query(c, "insert into tenant_role_template(tenant_id,name,description,scopes) values($1,$2,$3,$4) on conflict (tenant_id,name) do update set description=excluded.description, scopes=excluded.scopes", [actor.tenantId,name,description || null,assignedScopes])
		await query(c, "insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'role_template.upserted',$3,$4::jsonb)", [actor.tenantId,actor.userId,`role:${name}`,JSON.stringify({name,description,scopes:assignedScopes})])
	})
	revalidatePath("/settings/members")
}
