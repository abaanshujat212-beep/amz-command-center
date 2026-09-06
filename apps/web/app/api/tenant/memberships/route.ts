import { auth, authPool } from "@/lib/auth"

export const dynamic = "force-dynamic"

type Membership = { tenant_id: string; name: string; slug: string; role: string }

export async function GET(request: Request) {
	const session = await auth.api.getSession({ headers: request.headers })
	if (!session) return Response.json({ error: "Sign in required." }, { status: 401 })
	const { rows } = await authPool.query<Membership>(`select t.id::text as tenant_id,t.name,t.slug,m.role from public.tenant_member m join public.tenant t on t.id=m.tenant_id where m.user_id=$1 order by t.name`, [session.user.id])
	return Response.json({ memberships: rows })
}
