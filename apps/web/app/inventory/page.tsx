import Link from "next/link"
import { InventoryCsvImport } from "@/components/inventory-csv-import"
import { ManualInventoryForm } from "@/components/manual-inventory-form"
import { InventoryWorkspace } from "@/components/inventory-workspace"
import { withTenant } from "@/lib/db"
import { inventoryForecastRead, inventorySnapshotRead } from "@/lib/inventory"
import { inventoryFilters, type InventorySearch } from "@/lib/inventory-workspace"
import { mayManageTenant } from "@/lib/rbac"
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
	const locations = [...new Map(data.inventory.snapshots.map(row => [row.locationCode, { locationCode: row.locationCode, locationName: row.locationName }])).values()]
	return <div className="space-y-6"><InventoryWorkspace {...data} filters={filters} />{mayManageTenant(actor.role) ? <><ManualInventoryForm key={actor.tenantId} locations={locations} initialObservedAt={new Date().toISOString()} /><InventoryCsvImport key={`csv-${actor.tenantId}`} /></> : <p className="text-sm text-slate-500">Your role has read-only inventory access. Ask an owner or admin to record a stock count.</p>}</div>
}
