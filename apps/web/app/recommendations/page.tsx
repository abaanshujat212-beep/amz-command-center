import Link from "next/link"
import { withTenant } from "@/lib/db"
import { listRecommendations, parseRecommendationFilters, RecommendationQueryError } from "@/lib/recommendations"
import { confidenceLabel, recommendationPage, recommendationPageHref } from "@/lib/recommendation-filters"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

const TYPES = ["bid_adjustment", "budget_adjustment", "entity_state", "negative_targeting", "keyword_harvest", "placement_adjustment", "diagnostic"]
const STATUSES = ["pending", "approved", "applied", "verified", "rejected", "expired", "failed", "rolled_back"]
const RISKS = ["low", "medium", "high", "critical"]
const label = (value: string | null) => (value ?? "unclassified").replaceAll("_", " ")
const value = (raw: unknown) => raw && typeof raw === "object" && "value" in raw ? String((raw as { value: unknown }).value ?? "—") : raw == null ? "—" : String(raw)

export default async function Recommendations({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
	const raw = await searchParams
	const params = new URLSearchParams()
	for (const [key, item] of Object.entries(raw)) if (typeof item === "string") params.set(key, item)
	let error: string | null = null
	let result = recommendationPage<Awaited<ReturnType<typeof listRecommendations>>[number]>([], {limit: 50, offset: 0})
	try {
		const tenantId = await currentTenantId()
		const filters = parseRecommendationFilters(params)
		result = recommendationPage(await withTenant(tenantId, client => listRecommendations(client, tenantId, filters, true)), filters)
	} catch (cause) {
		if (cause instanceof RecommendationQueryError) error = cause.message
		else throw cause
	}
	const {recommendations, pagination} = result
	return <div className="space-y-5">
		<div><h1 className="text-lg font-semibold">Recommendation Center</h1><p className="mt-1 text-sm text-slate-600">Review grounded proposals, their expected effect, and operator risk before using the existing approval workflow.</p></div>
		<form method="get" className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-5">
			<Filter name="type" title="Type" values={TYPES} selected={params.get("type")} />
			<Filter name="status" title="Status" values={STATUSES} selected={params.get("status")} />
			<Filter name="risk" title="Risk" values={RISKS} selected={params.get("risk")} />
			<label className="text-xs font-medium text-slate-600">Minimum confidence<input name="minConfidence" type="number" min="0" max="1" step="0.05" defaultValue={params.get("minConfidence") ?? ""} className="mt-1 w-full rounded border border-slate-300 px-2 py-2 text-sm" /></label>
			<DateFilter name="from" title="Requested from (UTC)" selected={params.get("from")} />
			<DateFilter name="to" title="Requested through (UTC)" selected={params.get("to")} />
			{["confidence","entityType","entityId","limit"].map(key => params.has(key)
				? <input key={key} type="hidden" name={key} value={params.get(key) ?? ""} /> : null)}
			<div className="flex items-end gap-2"><button className="rounded bg-slate-900 px-4 py-2 text-sm text-white">Apply filters</button><Link href="/recommendations" className="px-2 py-2 text-sm text-slate-600">Clear</Link></div>
		</form>
		{error && <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">Invalid filters: {error}</div>}
		<div className="flex items-baseline justify-between"><h2 className="font-medium">Operator queue</h2><span className="text-xs text-slate-500">{recommendations.length ? `${pagination.offset + 1}–${pagination.offset + recommendations.length} shown` : "0 shown"}</span></div>
		{recommendations.length === 0 ? <div className="rounded-lg border border-slate-200 bg-white p-8 text-sm text-slate-600">No recommendations match these filters. Run the optimizer after fresh data is available, or broaden the filters.</div> :
		<ul className="space-y-3">{recommendations.map(item => <li key={item.id} className="rounded-lg border border-slate-200 bg-white p-4"><Link href={`/recommendations/${item.id}`} className="block">
			<div className="flex flex-wrap items-start justify-between gap-3"><div><div className="font-medium capitalize">{label(item.recommendation_type)}</div><div className="mt-1 text-sm text-slate-600">{item.action_type} · {item.entity_type} {item.entity_id}</div></div><div className="flex gap-2"><Badge text={item.status}/><Badge text={confidenceLabel(item.confidence)}/><Badge text={`${label(item.risk)} risk`} warn={item.risk === "high" || item.risk === "critical"}/></div></div>
			<p className="mt-3 text-sm">{item.reason_text ?? "No rationale was recorded."}</p><div className="mt-3 text-sm tabular-nums"><span className="text-slate-500">Current </span>{value(item.before_value)} <span className="mx-2 text-slate-400">→</span><span className="text-slate-500">Proposed </span><strong>{value(item.after_value)}</strong></div>
			{item.blocked_by && <p className="mt-2 text-xs text-amber-700">Conflict / dependency: {item.blocked_by}</p>}
		</Link></li>)}</ul>}
		{!error && (pagination.previousOffset !== null || pagination.nextOffset !== null) &&
			<nav aria-label="Recommendation pages" className="flex justify-between gap-3 text-sm">
				{pagination.previousOffset !== null && <Link className="rounded border px-3 py-2" href={recommendationPageHref(params,pagination.previousOffset)}>Previous page</Link>}
				{pagination.nextOffset !== null && <Link className="ml-auto rounded border px-3 py-2" href={recommendationPageHref(params,pagination.nextOffset)}>Next page</Link>}
			</nav>}
	</div>
}

function Filter({ name, title, values, selected }: { name: string; title: string; values: string[]; selected: string | null }) { return <label className="text-xs font-medium text-slate-600">{title}<select name={name} defaultValue={selected ?? ""} className="mt-1 w-full rounded border border-slate-300 bg-white px-2 py-2 text-sm"><option value="">All</option>{values.map(item => <option key={item} value={item}>{label(item)}</option>)}</select></label> }
function Badge({ text, warn = false }: { text: string; warn?: boolean }) { return <span className={`rounded-full px-2 py-1 text-xs capitalize ${warn ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-700"}`}>{text}</span> }


function DateFilter({ name, title, selected }: { name: string; title: string; selected: string | null }) {
	return <label className="text-xs font-medium text-slate-600">{title}<input name={name} type="date"
		defaultValue={selected ?? ""} className="mt-1 w-full rounded border border-slate-300 px-2 py-2 text-sm" /></label>
}
