import { query, withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"

const TYPES = new Set(["keyword", "search_term", "asin"])
const POLICIES = new Set(["allow", "deny", "protect"])
const DURATIONS = new Set(["one_time", "temporary", "persistent"])
function canManage(role: string) { return role === "owner" || role === "admin" }

export async function GET() {
	const actor = await currentContext()
	const rows = await withTenant(actor.tenantId, c => query(c, `select p.id,p.entity_type,p.entity_value,p.product_scope,p.policy,p.duration,p.expires_at,p.reason,p.created_by,p.created_at,(select e.event_type from entity_protection_event e where e.tenant_id=p.tenant_id and e.protection_id=p.id order by e.occurred_at desc,e.id desc limit 1) latest_event from entity_protection p order by p.created_at desc`))
	return Response.json({ protections: rows })
}

export async function POST(request: Request) {
	const actor = await currentContext()
	if (!canManage(actor.role)) return Response.json({ error: "owner_or_admin_required" }, { status: 403 })
	const body = await request.json() as Record<string, unknown>
	const entityType = String(body.entityType ?? ""), entityValue = String(body.entityValue ?? "").trim(), productScope = String(body.productScope ?? "*").trim() || "*"
	const policy = String(body.policy ?? ""), duration = String(body.duration ?? ""), reason = String(body.reason ?? "").trim()
	if (!TYPES.has(entityType) || !POLICIES.has(policy) || !DURATIONS.has(duration) || !entityValue || !reason) return Response.json({ error: "invalid_protection" }, { status: 400 })
	const expiresAt = duration === "temporary" ? String(body.expiresAt ?? "") : null
	if (duration === "temporary" && (!expiresAt || Number.isNaN(Date.parse(expiresAt)))) return Response.json({ error: "temporary_expiry_required" }, { status: 400 })
	const created = await withTenant(actor.tenantId, async c => {
		const rows = await query<{id:string}>(c, `insert into entity_protection(tenant_id,entity_type,entity_value,product_scope,policy,duration,expires_at,reason,created_by) values($1,$2,$3,$4,$5,$6,$7,$8,$9) returning id`, [actor.tenantId,entityType,entityValue,productScope,policy,duration,expiresAt,reason,actor.userId])
		await query(c, `insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'entity_protection.created',$3,$4::jsonb)`, [actor.tenantId,actor.userId,`${entityType}:${entityValue}`,JSON.stringify({productScope,policy,duration,expiresAt,reason})])
		return rows[0]
	})
	return Response.json(created, { status: 201 })
}

export async function DELETE(request: Request) {
	const actor = await currentContext()
	if (!canManage(actor.role)) return Response.json({ error: "owner_or_admin_required" }, { status: 403 })
	const body = await request.json() as Record<string, unknown>, id = String(body.id ?? ""), reason = String(body.reason ?? "").trim()
	if (!id || !reason) return Response.json({ error: "id_and_reason_required" }, { status: 400 })
	const released = await withTenant(actor.tenantId, async c => {
		const rows = await query<{id:string}>(c, "select id from entity_protection where tenant_id=$1 and id=$2", [actor.tenantId,id])
		if (!rows.length) return false
		await query(c, `insert into entity_protection_event(tenant_id,protection_id,event_type,reason,actor_user_id) values($1,$2,'released',$3,$4)`, [actor.tenantId,id,reason,actor.userId])
		await query(c, `insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'entity_protection.released',$3,$4::jsonb)`, [actor.tenantId,actor.userId,`protection:${id}`,JSON.stringify({reason})])
		return true
	})
	return released ? Response.json({ status: "released" }) : Response.json({ error: "not_found" }, { status: 404 })
}
