import { auth, authPool } from "@/lib/auth"

export const dynamic = "force-dynamic"

type Membership = { tenant_id: string; name: string; slug: string; role: string }

export async function GET(request: Request) {
	const session = await auth.api.getSession({ headers: request.headers })
	if (!session) return Response.json({ error: "Sign in required." }, { status: 401 })
	const { rows } = await authPool.query<Membership>("select * from public.session_memberships($1)", [session.session.token])
	return Response.json({ memberships: rows })
}
