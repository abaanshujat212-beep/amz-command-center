import { auth, authPool } from "@/lib/auth"

export const dynamic = "force-dynamic"

type Tenant = { tenant_id: string; name: string; slug: string; role: string }
type Workspace = { workspace_id: string; name: string; slug: string; role: string; can_operate_tenants: boolean; portfolio_enabled: boolean }

export async function GET(request: Request) {
	const session = await auth.api.getSession({ headers: request.headers })
	if (!session) return Response.json({ error: "Sign in required." }, { status: 401 })
	const [tenants, workspaces] = await Promise.all([
		authPool.query<Tenant>("select * from public.session_memberships($1)", [session.session.token]),
		authPool.query<Workspace>("select * from public.session_workspaces($1)", [session.session.token]),
	])
	return Response.json({
		tenants: tenants.rows,
		workspaces: workspaces.rows.filter(w => w.portfolio_enabled && w.can_operate_tenants),
	})
}
