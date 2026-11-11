type WindowStatus = "complete" | "partial" | "no_data" | "invalid"
type SourceFreshness = "current" | "stale" | "unknown"
export type VelocityEvidence = {
	windowDays: number; startDay: string; endDay: string; observedDays: number; missingDays: number;
	status: WindowStatus; unitsObserved: number | null; averageDailyUnitsObserved: number | null;
	invalidRows: number; numericRangeExceeded: boolean; salesFreshness: SourceFreshness;
	salesLoadedAt: string | null; latestSalesDate: string | null;
}
const windows = [["7d", 7], ["14d", 14], ["30d", 30]] as const
const statusLabels: Record<WindowStatus, string> = { complete: "Complete history", partial: "Partial history", no_data: "No observations", invalid: "Invalid sales evidence" }
function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value) }
function day(value: unknown): value is string {
	if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
	const date = new Date(`${value}T00:00:00Z`)
	return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}
function count(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 }
function amount(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= Number.MAX_SAFE_INTEGER }

/** Fail closed when optional or malformed window evidence is returned by an older API. */
export function velocityEvidence(value: unknown, expectedDays: number, now = Date.now()): VelocityEvidence | null {
	if (!record(value) || value.windowDays !== expectedDays || !day(value.startDay) || !day(value.endDay)) return null
	if ((Date.parse(value.endDay) - Date.parse(value.startDay)) / 86400000 !== expectedDays - 1 || value.endDay >= new Date(now).toISOString().slice(0, 10)) return null
	if (!count(value.observedDays) || !count(value.missingDays) || value.observedDays + value.missingDays !== expectedDays || !count(value.invalidRows)) return null
	if (typeof value.status !== "string" || !Object.hasOwn(statusLabels, value.status)) return null
	let status = value.status as WindowStatus
	const numericRangeExceeded = value.numericRangeExceeded === true
	if (value.invalidRows > 0 || numericRangeExceeded) status = "invalid"
	if ((status === "complete" && value.missingDays !== 0) || (status === "partial" && (value.observedDays === 0 || value.missingDays === 0)) || (status === "no_data" && value.observedDays !== 0)) return null
	const knownStats = (status === "complete" || status === "partial") && amount(value.unitsObserved) && amount(value.averageDailyUnitsObserved)
	if ((status === "complete" || status === "partial") && !knownStats) return null
	let salesFreshness: SourceFreshness = value.salesFreshness === "current" || value.salesFreshness === "stale" ? value.salesFreshness : "unknown"
	const loaded = typeof value.salesLoadedAt === "string" ? Date.parse(value.salesLoadedAt) : NaN
	const salesLoadedAt = Number.isFinite(loaded) ? new Date(loaded).toISOString() : null
	const latestSalesDate = day(value.latestSalesDate) && value.latestSalesDate >= value.startDay && value.latestSalesDate <= value.endDay ? value.latestSalesDate : null
	if (!salesLoadedAt || loaded > now || !latestSalesDate || status === "no_data") salesFreshness = "unknown"
	return {
		windowDays: expectedDays, startDay: value.startDay, endDay: value.endDay,
		observedDays: value.observedDays, missingDays: value.missingDays, status,
		unitsObserved: knownStats ? value.unitsObserved as number : null,
		averageDailyUnitsObserved: knownStats ? value.averageDailyUnitsObserved as number : null,
		invalidRows: value.invalidRows, numericRangeExceeded, salesFreshness, salesLoadedAt, latestSalesDate,
	}
}
function units(value: number | null) {
	if (value === null) return "Unknown"
	if (value > 0 && value < 0.0001) return "<0.0001"
	return value.toLocaleString("en-GB", { maximumFractionDigits: 4 })
}
function loadedAt(value: string | null) { return value ? `${value.slice(0, 16).replace("T", " ")} UTC` : "Unknown" }

export function InventoryVelocityEvidence({ evidence, coverageBlocked }: { evidence?: unknown; coverageBlocked: boolean }) {
	const values = record(evidence) ? evidence : {}
	const normalized = windows.map(([key, days]) => ({ key, days, data: velocityEvidence(values[key], days) }))
	return <section aria-label="Historical sales evidence" className="mt-4 border-t pt-4">
		<h4 className="text-sm font-medium">Historical sales evidence</h4>
		<p className="mt-1 text-xs text-slate-600">Completed UTC days only. Missing dates are not counted as zero sales.{coverageBlocked ? " Coverage remains unavailable until its warnings are resolved." : " These figures describe observed sales, not a reorder recommendation."}</p>
		<div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-3">{normalized.map(({ key, days, data }) => <div key={key} className="min-w-0 rounded border border-slate-200 p-3 text-xs">
			<h5 className="font-semibold">{days}-day window</h5>
			{!data ? <p className="mt-2 text-slate-500">Evidence unavailable</p> : <>
				<p className="mt-1 break-words text-slate-500">{data.startDay} – {data.endDay} UTC</p>
				<p className={`mt-2 font-medium ${data.status === "complete" && data.salesFreshness === "current" ? "text-slate-700" : "text-amber-800"}`}>{statusLabels[data.status]}</p>
				<dl className="mt-2 space-y-1"><div className="flex flex-wrap justify-between gap-x-2"><dt>Observed / missing days</dt><dd>{data.observedDays} / {data.missingDays}</dd></div><div className="flex flex-wrap justify-between gap-x-2"><dt>Observed units</dt><dd>{units(data.unitsObserved)}</dd></div><div className="flex flex-wrap justify-between gap-x-2"><dt>Average / observed day</dt><dd>{units(data.averageDailyUnitsObserved)}</dd></div><div className="flex flex-wrap justify-between gap-x-2"><dt>Source freshness</dt><dd>{data.salesFreshness}</dd></div></dl>
				{data.status === "partial" && <p className="mt-2 text-amber-800">Partial history: this average covers observed days only.</p>}
				{data.status === "invalid" && <p className="mt-2 text-amber-800">{data.numericRangeExceeded ? "Sales quantities exceed the supported precision." : "Invalid sales rows prevent a reliable total or average."}</p>}
				{data.salesFreshness !== "current" && <p className="mt-2 text-amber-800">{data.salesFreshness === "stale" ? "Stale source: verify newer observations before using this history." : "Source freshness is unknown; verify the observations."}</p>}
				<p className="mt-2 break-words text-slate-500">Latest sales date: {data.latestSalesDate ?? "Unknown"}<br />Loaded: {loadedAt(data.salesLoadedAt)}</p>
			</>}
		</div>)}</div>
	</section>
}
