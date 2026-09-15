import { auth, authPool } from "@/lib/auth"
import { assertBusinessHierarchy, assertWorkspaceOperation, safeReturnRoute, type BusinessContext } from "@/lib/business-context"
import { assertMembership } from "@/lib/db"

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
function optionalId(value: unknown) { if (value == null || value === "") return null; if (typeof value !== "string" || !UUID.test(value)) throw new Error("invalid context identifier"); return value }

export async function POST(request: Request) {
	const session = await auth.api.getSession({ headers: request.headers })
	if (!session) return Response.json({ error: "Sign in required." }, { status: 401 })
	const body = await request.json().catch(() => null) as Record<string, unknown> | null
	const tenantId = typeof body?.tenantId === "string" ? body.tenantId.trim() : ""
	if (!UUID.test(tenantId)) return Response.json({ error: "A valid tenant ID is required." }, { status: 400 })
	let context: BusinessContext
	try {
		context = { workspaceId: optionalId(body?.workspaceId), brandId: optionalId(body?.brandId), channelAccountId: optionalId(body?.channelAccountId), marketplaceContextId: optionalId(body?.marketplaceContextId), adsProfileId: optionalId(body?.adsProfileId) }
		await assertMembership(tenantId, session.user.id)
		if (context.workspaceId) await assertWorkspaceOperation(session.session.token, context.workspaceId, tenantId)
		await assertBusinessHierarchy(tenantId, context)
	} catch { return Response.json({ error: "The requested account context is not authorized." }, { status: 403 }) }
	await authPool.query(`update auth_session set active_tenant_id=$1,active_workspace_id=$2,active_brand_id=$3,active_channel_account_id=$4,active_marketplace_context_id=$5,active_ads_profile_id=$6,updated_at=now() where id=$7 and user_id=$8`, [tenantId,context.workspaceId,context.brandId,context.channelAccountId,context.marketplaceContextId,context.adsProfileId,session.session.id,session.user.id])
	return Response.json({ ok: true, tenantId, returnTo: safeReturnRoute(body?.returnTo) })
}
