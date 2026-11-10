import { withTenant } from "@/lib/db"
import { inventoryForecastRead } from "@/lib/inventory"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
	const actor = await currentContext()
	const value = Number.parseInt(new URL(request.url).searchParams.get("freshHours") ?? "72", 10)
	if (!Number.isInteger(value) || value < 1 || value > 8760) {
		return Response.json({ error: "freshHours must be between 1 and 8760." }, { status: 400 })
	}
	const forecasts = await withTenant(actor.tenantId, client => inventoryForecastRead(client, actor.tenantId, value))
	return Response.json({ forecasts, freshnessThresholdHours: value })
}
