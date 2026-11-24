import Link from "next/link"
import { loadOperatorAlerts } from "@/lib/operator-alerts"
import { ALERT_SEVERITIES, operatorAlertFilters, type AlertSeverity } from "@/lib/operator-alerts-contract"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"
const tone: Record<AlertSeverity, string> = {
	critical: "bg-red-50 text-red-800", warning: "bg-amber-50 text-amber-900", info: "bg-sky-50 text-sky-800",
}
const timestamp = (value: string) => new Intl.DateTimeFormat("en-GB", {
	dateStyle: "medium", timeStyle: "short", timeZone: "UTC",
}).format(new Date(value)) + " UTC"

export default async function OperatorAlerts({ searchParams }: {
	searchParams: Promise<{ severity?: string | string[] }>
}) {
	const tenantId = await currentTenantId()
	const params = new URLSearchParams()
	const { severity } = await searchParams
	for (const value of typeof severity === "string" ? [severity] : severity ?? []) params.append("severity", value)
	params.set("limit", "50")
	const filters = operatorAlertFilters(params)
	const data = filters ? await loadOperatorAlerts(tenantId, filters) : null
	return <div className="space-y-4">
		<div>
			<h1 className="text-lg font-semibold">Operator alerts</h1>
			<p className="text-sm text-slate-600">Open blockers for the active tenant. These alerts are tenant-wide, not limited to the selected account.</p>
		</div>
		<nav aria-label="Filter alerts by severity" className="flex flex-wrap gap-2">
			{([null, ...ALERT_SEVERITIES] as const).map(level => <Link key={level ?? "all"}
				href={level ? `/alerts?severity=${level}` : "/alerts"}
				aria-current={filters?.severity === level ? "page" : undefined}
				className={filters?.severity === level ? "rounded border bg-slate-900 px-3 py-2 text-sm capitalize text-white" : "rounded border bg-white px-3 py-2 text-sm capitalize text-slate-800"}>
				{level ?? "All"}
			</Link>)}
		</nav>
		{!data ? <p className="rounded border bg-white p-4 text-sm" role="status">Choose a supported severity filter.</p> : <>
			<p className="text-xs text-slate-600">Checked <time dateTime={data.shownThrough}>{timestamp(data.shownThrough)}</time>.{data.hasMore && " Showing the first 50 alerts. Use the filters or review more details in Run history."}</p>
			{data.items.length === 0 ? <p className="rounded border bg-white p-4 text-sm">No open alerts match this filter.</p> : <ul className="grid gap-3">
				{data.items.map(item => <li key={item.id} className="rounded border bg-white p-4">
					<div className="flex flex-wrap items-center gap-2">
						<p className={`rounded px-2 py-1 text-xs capitalize ${tone[item.severity]}`}>{item.severity}</p>
						<h2 className="font-medium">{item.title}</h2>
					</div>
					<p className="mt-1 text-xs text-slate-600">{item.source} · <time dateTime={item.occurredAt}>{timestamp(item.occurredAt)}</time></p>
					<p className="mt-2 text-sm text-slate-700">{item.nextStep}</p>
					<Link className="mt-2 inline-block text-sm font-medium text-blue-800 underline" href={item.recovery.href}>{item.recovery.label}</Link>
				</li>)}
			</ul>}
		</>}
	</div>
}
