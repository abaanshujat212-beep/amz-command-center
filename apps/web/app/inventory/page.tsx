import Link from "next/link"
import { InventoryWorkspace } from "@/components/inventory-workspace"
import { withTenant } from "@/lib/db"
import { inventoryForecastRead, inventorySnapshotRead } from "@/lib/inventory"
import { inventoryFilters, type InventorySearch } from "@/lib/inventory-workspace"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export default async function InventoryPage({ searchParams }: { searchParams: Promise<InventorySearch> }) {
	const actor = await currentContext()
	const filters = inventoryFilters(await searchParams)
	if (!filters) return <div className="space-y-3"><h1 className="text-lg font-semibold">Inventory</h1><p role="alert" className="rounded border border-amber-200 bg-amber-50 p-4 text-sm">Invalid filters. SKU and location must be at most 100 characters; page must be a positive integer and freshness must be 1–8760 hours.</p><Link href="/inventory" className="text-sm text-blue-700 underline">Reset filters</Link></div>
	const data = await withTenant(actor.tenantId, async client => {
		const inventory = await inventorySnapshotRead(client, actor.tenantId, filters)
		const forecasts = await inventoryForecastRead(client, actor.tenantId, filters.freshHours)
		const visibleSkus = new Set(inventory.snapshots.map(row => row.sku))
		return { inventory, forecasts: forecasts.filter(row => visibleSkus.has(row.sku)) }
	})
	return <InventoryWorkspace {...data} filters={filters} />
}
