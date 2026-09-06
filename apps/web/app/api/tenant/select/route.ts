import { auth, authPool } from "@/lib/auth"
import { assertMembership } from "@/lib/db"

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export async function POST(request: Request) {
	const session = await auth.api.getSession({ headers: request.headers })
	if (!session) return Response.json({ error: "Sign in required." }, { status: 401 })
	const body = await request.json().catch(() => null) as { tenantId?: unknown } | null
	const tenantId = typeof body?.tenantId === "string" ? body.tenantId.trim() : ""
	if (!UUID.test(tenantId)) return Response.json({ error: "A valid tenant ID is required." }, { status: 400 })
	try { await assertMembership(tenantId, session.user.id) } catch { return Response.json({ error: "You are not a member of that tenant." }, { status: 403 }) }
	await authPool.query("update auth_session set active_tenant_id = $1, updated_at = now() where id = $2 and user_id = $3", [tenantId, session.session.id, session.user.id])
	return Response.json({ ok: true, tenantId })
}
