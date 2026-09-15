import { auth } from "@/lib/auth"
import { portfolioSummary } from "@/lib/portfolio"

export const dynamic = "force-dynamic"
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export async function GET(request: Request) {
	const session = await auth.api.getSession({ headers: request.headers })
	if (!session) return Response.json({ error: "Sign in required." }, { status: 401 })
	const url = new URL(request.url)
	const workspaceId = url.searchParams.get("workspaceId") ?? ""
	if (!UUID.test(workspaceId)) return Response.json({ error: "A valid workspace ID is required." }, { status: 400 })
	const page = Math.max(1, Number.parseInt(url.searchParams.get("page") ?? "1", 10) || 1)
	const pageSize = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("pageSize") ?? "25", 10) || 25))
	const includeAttention = url.searchParams.get("includeAttention") === "true"
	const summary = await portfolioSummary(session.session.token, workspaceId, page, pageSize, includeAttention)
	if (summary.total === 0) return Response.json({ error: "No authorized accounts are available for this workspace." }, { status: 403 })
	return Response.json(summary)
}
