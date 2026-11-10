import { withTenant } from "@/lib/db"
import { inventorySnapshotRead } from "@/lib/inventory"
import { currentContext } from "@/lib/session"

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
