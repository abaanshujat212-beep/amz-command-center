import Link from "next/link"
import { InventoryVelocityEvidence } from "@/components/inventory-velocity-evidence"
import type { inventoryForecastRead, inventorySnapshotRead } from "@/lib/inventory"
import { inventoryPageHref, type InventoryFilters } from "@/lib/inventory-workspace"

type Props = {
	inventory: Awaited<ReturnType<typeof inventorySnapshotRead>>
	forecasts: Awaited<ReturnType<typeof inventoryForecastRead>>
	filters: InventoryFilters
}

function quantity(value: number | null) {
	return value === null || !Number.isFinite(value) ? "Unknown" : value.toLocaleString("en-GB", { maximumFractionDigits: 2 })
}
function timestamp(value: string | null) {
	if (!value) return "Unknown"
	const date = new Date(value)
	return Number.isNaN(date.getTime()) ? "Unknown" : `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`
}
function label(value: string) { return value.replaceAll("_", " ") }
function Freshness({ state }: { state: string }) {
	return <span className={`inline-block rounded px-2 py-1 text-xs font-medium ${(state === "current" || state === "ready") ? "bg-green-50 text-green-800" : "bg-amber-50 text-amber-900"}`}>{label(state)}</span>
}
const th = "whitespace-nowrap p-3 text-left text-xs font-medium uppercase text-slate-500"
const td = "p-3 align-top"

export function InventoryWorkspace({ inventory, forecasts, filters }: Props) {
	const { snapshots, pagination } = inventory
	const freshness = snapshots.reduce((counts, row) => {
		counts[row.freshness] += 1
		return counts
	}, { current: 0, stale: 0, partial: 0, unknown: 0 })
	const pages = Math.max(1, Math.ceil(pagination.total / pagination.pageSize))
	return <div className="space-y-6">
		<header><h1 className="text-xl font-semibold">Inventory</h1><p className="mt-1 text-sm text-slate-600">Available stock, expected arrivals and source evidence across your active locations.</p></header>
		<form action="/inventory" method="get" className="flex flex-wrap items-end gap-3 rounded-lg border bg-white p-4">
			<label className="grid gap-1 text-sm">SKU<input name="sku" defaultValue={filters.sku} maxLength={100} placeholder="Exact SKU" className="rounded border px-3 py-2" /></label>
			<label className="grid gap-1 text-sm">Location code<input name="location" defaultValue={filters.locationCode} maxLength={100} placeholder="Exact location code" className="rounded border px-3 py-2" /></label>
			<label className="grid gap-1 text-sm">Freshness limit (hours)<input name="freshHours" defaultValue={filters.freshHours} type="number" min={1} max={8760} required className="w-36 rounded border px-3 py-2" /></label>
			<button className="rounded bg-slate-900 px-4 py-2 text-sm text-white">Apply filters</button><Link href="/inventory" className="px-2 py-2 text-sm text-blue-700 underline">Reset</Link>
		</form>
		<section aria-label="Inventory evidence on this page" className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[["Matching positions", pagination.total], ["Current on this page", freshness.current], ["Stale on this page", freshness.stale], ["Partial / unknown on this page", freshness.partial + freshness.unknown]].map(([title, value]) => <div key={title} className="rounded-lg border bg-white p-4"><p className="text-xs text-slate-500">{title}</p><p className="mt-1 text-2xl font-semibold">{value}</p></div>)}</section>
		<section className="space-y-3"><div><h2 className="font-semibold">Location positions</h2><p className="text-sm text-slate-600">Unknown quantities are not zero. Inbound and in-transit units are separate from stock available now.</p></div>
		<div className="overflow-x-auto rounded-lg border bg-white"><table className="w-full text-sm"><caption className="sr-only">Latest inventory observations by SKU and location</caption><thead className="border-b bg-slate-50"><tr>{["SKU / location", "Available now", "On hand", "Reserved / committed", "Inbound / in transit", "Source & freshness"].map(title => <th key={title} scope="col" className={th}>{title}</th>)}</tr></thead><tbody>{snapshots.map(row => <tr key={row.snapshotId} className="border-b last:border-0">
			<td className={td}><b>{row.sku}</b><div>{row.locationName}</div><div className="text-xs text-slate-500">{row.locationCode} · {label(row.locationType)}</div>{row.marketplaceId && <div className="text-xs text-slate-500">{row.marketplaceId}</div>}</td>
			<td className={`${td} font-semibold`}>{quantity(row.availableQty)}</td><td className={td}>{quantity(row.onHandQty)}</td>
			<td className={td}><div>Reserved: {quantity(row.reservedQty)}</div><div>Committed: {quantity(row.committedQty)}</div><div className="text-xs text-slate-500">Unsellable: {quantity(row.unsellableQty)}</div></td>
			<td className={td}><div>Inbound: {quantity(row.inboundQty)}</div><div>In transit: {quantity(row.inTransitQty)}</div><div className="mt-1 text-xs text-slate-500">Expected availability: {timestamp(row.expectedAvailableAt)}</div></td>
			<td className={td}><Freshness state={row.freshness} /><div className="mt-1">{label(row.sourceType)}</div>{row.sourceProviderId && <div className="text-xs text-slate-500">Provider: {row.sourceProviderId}</div>}<div className="text-xs text-slate-500">Observed: {timestamp(row.observedAt)}</div><details className="mt-1 text-xs text-slate-500"><summary className="cursor-pointer">Source reference</summary><p className="max-w-xs break-all py-1">{row.sourceReference}</p></details></td>
		</tr>)}</tbody></table>{!snapshots.length && <div className="p-6 text-sm text-slate-600">{pagination.total ? "No positions on this page. Use Previous or reset the filters." : "No inventory observations match these filters. Stock and coverage remain unknown until source observations are available."}</div>}</div>
		<nav aria-label="Inventory pagination" className="flex flex-wrap items-center justify-between gap-3 text-sm"><span>Page {pagination.page} of {pages} · {pagination.total} matching positions</span><div className="flex gap-3">{pagination.page > 1 && <Link href={inventoryPageHref(filters, pagination.page - 1)} className="rounded border bg-white px-3 py-2">Previous</Link>}{pagination.page < pages && <Link href={inventoryPageHref(filters, pagination.page + 1)} className="rounded border bg-white px-3 py-2">Next</Link>}</div></nav>
		</section>
		<section className="space-y-3"><div><h2 className="font-semibold">Stock coverage</h2><p className="text-sm text-slate-600">SKUs on this page, across all active locations. A location filter changes the positions above; coverage still uses all locations.</p></div>
		<div className="grid gap-4 xl:grid-cols-2">{forecasts.map(row => <article key={row.sku} className="rounded-lg border bg-white p-4"><div className="flex items-center justify-between gap-3"><h3 className="font-semibold">{row.sku}</h3><Freshness state={row.status} /></div>{row.blockers.length > 0 && <div className="mt-3 rounded bg-amber-50 p-3 text-sm text-amber-900"><p className="font-medium">Coverage unavailable</p><ul className="mt-1 list-inside list-disc">{row.blockers.map(reason => <li key={reason}>{label(reason)}</li>)}</ul></div>}
			<dl className="mt-3 grid grid-cols-2 gap-3 text-sm"><div><dt className="text-slate-500">Available now</dt><dd>{quantity(row.availableNow)}</dd></div><div><dt className="text-slate-500">Average units / day</dt><dd>{row.status === "ready" ? quantity(row.averageDailyDemand) : "Unavailable"}</dd></div><div><dt className="text-slate-500">Days of supply</dt><dd>{row.status === "ready" ? quantity(row.daysOfSupply) : "Unavailable"}</dd></div><div><dt className="text-slate-500">Projected stockout</dt><dd>{row.status === "ready" ? row.projectedStockoutDay ?? "Unknown" : "Unavailable"}</dd></div></dl>
			<InventoryVelocityEvidence evidence={"velocityWindows" in row.assumptions ? row.assumptions.velocityWindows : undefined} coverageBlocked={row.status !== "ready"} />
			<details className="mt-4 text-xs text-slate-600"><summary className="cursor-pointer font-medium">Evidence & assumptions</summary><dl className="mt-2 grid gap-1"><div className="flex justify-between gap-3"><dt>Observed sales days</dt><dd>{row.assumptions.observedSalesDays} / {row.assumptions.demandWindowDays}</dd></div><div className="flex justify-between gap-3"><dt>Inventory observed</dt><dd>{timestamp(row.assumptions.inventoryObservedAt)}</dd></div><div className="flex justify-between gap-3"><dt>Sales loaded</dt><dd>{timestamp(row.assumptions.salesLoadedAt)}</dd></div><div className="flex justify-between gap-3"><dt>Confidence</dt><dd>{Math.round(row.confidence * 100)}%</dd></div><div className="flex justify-between gap-3"><dt>Seasonality</dt><dd>{label(row.assumptions.seasonality)}</dd></div><div className="flex justify-between gap-3"><dt>Lead time</dt><dd>{label(row.assumptions.leadTime)}</dd></div></dl></details>
		</article>)}</div>{!forecasts.length && <p className="rounded-lg border bg-white p-4 text-sm text-slate-600">No coverage estimates for the positions on this page.</p>}
		</section>
	</div>
}
