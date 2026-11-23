import { loadOperatorAlerts } from "@/lib/operator-alerts"
import { operatorAlertFilters } from "@/lib/operator-alerts-contract"
import { AuthenticationRequired, currentContext, TenantSelectionRequired } from "@/lib/session"

export const dynamic = "force-dynamic"
const headers = { "Cache-Control": "private, no-store" }

export async function GET(request: Request) {
	let actor
	try {
		actor = await currentContext()
	} catch (error) {
		const status = error instanceof AuthenticationRequired ? 401 : error instanceof TenantSelectionRequired ? 409 : 403
		const message = status === 401 ? "Sign in to view alerts." : status === 409 ? "Select a tenant to view alerts." : "Alert access is unavailable."
		return Response.json({ error: message }, { status, headers })
	}
	const filters = operatorAlertFilters(new URL(request.url).searchParams)
	if (!filters) return Response.json({ error: "Choose a supported severity and a limit of 1 to 50." }, { status: 400, headers })
	try {
		return Response.json(await loadOperatorAlerts(actor.tenantId, filters), { headers })
	} catch {
		return Response.json({ error: "Alerts are temporarily unavailable." }, { status: 503, headers })
	}
}
