import { withTenant } from "@/lib/db"
import { AuthenticationRequired, currentContext, TenantSelectionRequired } from "@/lib/session"
import { assertManualInventoryRole, InventoryIntakeError, readInventoryIntakeBody } from "@/lib/inventory-intake"
import { commitInventoryCsv, INVENTORY_CSV_JSON_BYTES, InventoryCsvError, parseInventoryCsvRequest, previewInventoryCsv } from "@/lib/inventory-csv"

export const dynamic = "force-dynamic"

export async function POST(request: Request) {
	try {
		const actor = await currentContext()
		assertManualInventoryRole(actor.role)
		const input = parseInventoryCsvRequest(await readInventoryIntakeBody(request, INVENTORY_CSV_JSON_BYTES))
		if (input.mode === "preview") return Response.json(previewInventoryCsv(input.csv))
		const result = await withTenant(actor.tenantId, client => commitInventoryCsv(client, actor, input.csv))
		return Response.json(result)
	} catch (error) {
		if (error instanceof InventoryCsvError) return Response.json({ error: error.message, ...error.details }, { status: error.status })
		if (error instanceof InventoryIntakeError) return Response.json({ error: error.message }, { status: error.status })
		if (error instanceof AuthenticationRequired) return Response.json({ error: error.message }, { status: 401 })
		if (error instanceof TenantSelectionRequired) return Response.json({ error: error.message }, { status: 409 })
		throw error
	}
}
