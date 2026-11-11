import { withTenant } from "@/lib/db"
import { inventorySnapshotRead } from "@/lib/inventory"
import { AuthenticationRequired, currentContext, TenantSelectionRequired } from "@/lib/session"
import { assertManualInventoryRole, InventoryIntakeError, readInventoryIntakeBody, recordManualInventory } from "@/lib/inventory-intake"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
	const actor = await currentContext()
	const url = new URL(request.url)
	const pageValue = Number.parseInt(url.searchParams.get("page") ?? "1", 10)
	const pageSizeValue = Number.parseInt(url.searchParams.get("pageSize") ?? "50", 10)
	const freshHoursValue = Number.parseInt(url.searchParams.get("freshHours") ?? "72", 10)
	if (!Number.isInteger(pageValue) || pageValue < 1 || !Number.isInteger(pageSizeValue) || pageSizeValue < 1 ||
		!Number.isInteger(freshHoursValue) || freshHoursValue < 1 || freshHoursValue > 8760) {
		return Response.json({ error: "Invalid pagination or freshness threshold." }, { status: 400 })
	}
	const sku = url.searchParams.get("sku")?.trim() || undefined
	const locationCode = url.searchParams.get("location")?.trim() || undefined
	if ((sku?.length ?? 0) > 100 || (locationCode?.length ?? 0) > 100) {
		return Response.json({ error: "SKU and location filters must be at most 100 characters." }, { status: 400 })
	}
	const inventory = await withTenant(actor.tenantId, client => inventorySnapshotRead(
		client, actor.tenantId, {
			sku, locationCode, page: pageValue, pageSize: Math.min(100, pageSizeValue), freshHours: freshHoursValue,
		},
	))
	return Response.json(inventory)
}


export async function POST(request: Request) {
	try {
		const actor = await currentContext()
		assertManualInventoryRole(actor.role)
		const body = await readInventoryIntakeBody(request)
		const snapshot = await withTenant(actor.tenantId, client => recordManualInventory(client, actor, body))
		return Response.json({ snapshot }, { status: snapshot.inserted ? 201 : 200 })
	} catch (error) {
		if (error instanceof InventoryIntakeError) return Response.json({ error: error.message }, { status: error.status })
		if (error instanceof AuthenticationRequired) return Response.json({ error: error.message }, { status: 401 })
		if (error instanceof TenantSelectionRequired) return Response.json({ error: error.message }, { status: 409 })
		throw error
	}
}
