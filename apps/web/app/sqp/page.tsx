import { SearchIntelligenceNav } from "@/components/search-intelligence-nav"
import { withTenant } from "@/lib/db"
import { count, money, percent } from "@/lib/format"
import { sqpOpportunities } from "@/lib/queries"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

const ACTIONS = ["all", "harvest_exact", "test_campaign", "watch_spend", "monitor", "already_negative"]

export default async function Sqp({ searchParams }: { searchParams: Promise<{ action?: string }> }) {
	const requested = (await searchParams).action ?? "all"
	const action = ACTIONS.includes(requested) ? requested : "all"
	const rows = await withTenant(await currentTenantId(), client => sqpOpportunities(client, action))
	const windowStart = rows.length ? rows.reduce((value, row) => value < row.window_start ? value : row.window_start, rows[0].window_start) : null
	const windowEnd = rows.length ? rows.reduce((value, row) => value > row.window_end ? value : row.window_end, rows[0].window_end) : null
	const loadedAt = rows.length ? rows.reduce((value, row) => value > row.source_loaded_at ? value : row.source_loaded_at, rows[0].source_loaded_at) : null

	return <div className="space-y-4">
		<SearchIntelligenceNav active="/sqp" />
		<div><h1 className="text-lg font-semibold">Own-product search intelligence</h1><p className="text-sm text-slate-600">Read-only observations from Amazon Search Query Performance for your ASINs, joined to your Ads data. This is not a market-wide trend estimate.</p></div>
		<div className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 text-xs text-slate-600 sm:grid-cols-5">
			<div><b className="block text-slate-900">Source</b>Amazon SQP + Amazon Ads</div>
			<div><b className="block text-slate-900">Scope</b>Your eligible ASINs only</div>
			<div><b className="block text-slate-900">Grain</b>Query by ASIN, rolling window</div>
			<div><b className="block text-slate-900">Observed</b>{windowStart && windowEnd ? `${windowStart} to ${windowEnd}` : "No SQP rows"}</div>
			<div><b className="block text-slate-900">Loaded</b>{loadedAt ? new Date(loadedAt).toLocaleString("en-GB", { timeZone: "UTC" }) + " UTC" : "No SQP rows"}</div>
		</div>
		<form><select name="action" defaultValue={action} className="rounded border px-2 py-1 text-sm">{ACTIONS.map(value => <option key={value}>{value}</option>)}</select><button className="ml-2 rounded bg-slate-900 px-3 py-1 text-sm text-white">Filter</button></form>
		<div className="overflow-x-auto rounded border bg-white"><table className="w-full text-sm"><thead><tr className="border-b text-left text-xs uppercase text-slate-500"><th className="p-3">Score / query</th><th className="p-3 num">Volume</th><th className="p-3 num">CTR / CVR</th><th className="p-3 num">Ads</th><th className="p-3">Suggested action</th></tr></thead><tbody>{rows.map(row => <tr key={`${row.asin}:${row.search_query}`} className="border-b"><td className="p-3"><b>{row.sqp_opportunity_score}</b> · {row.search_query}<div className="text-xs text-slate-500">{row.asin}{row.exists_as_exact ? " · exact exists" : " · not exact"}</div></td><td className="p-3 num">{count(row.query_volume_30d)}</td><td className="p-3 num">{percent(row.query_ctr)} / {percent(row.query_cvr)}</td><td className="p-3 num">{money(row.ad_spend_30d)}<div className="text-xs text-slate-500">ACOS {percent(row.ads_acos)}</div></td><td className="p-3"><span className="rounded bg-slate-100 px-2 py-1 font-mono text-xs">{row.suggested_action}</span>{row.economics_incomplete && <div className="mt-1 text-xs tone-warn">economics missing</div>}</td></tr>)}</tbody></table></div>
	</div>
}
