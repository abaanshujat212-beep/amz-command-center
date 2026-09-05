import { withTenant } from "@/lib/db"
import { count, money, percent } from "@/lib/format"
import { sqpOpportunities } from "@/lib/queries"
import { currentTenantId } from "@/lib/session"
export const dynamic = "force-dynamic"
const ACTIONS = ["all", "harvest_exact", "test_campaign", "watch_spend", "monitor", "already_negative"]
export default async function Sqp({ searchParams }: { searchParams: Promise<{ action?: string }> }) {
	const requested = (await searchParams).action ?? "all"
	const action = ACTIONS.includes(requested) ? requested : "all"
	const rows = await withTenant(await currentTenantId(), c => sqpOpportunities(c, action))
	return <div className="space-y-4"><div><h1 className="text-lg font-semibold">SQP opportunity finder</h1><p className="text-sm text-slate-600">Read-only suggestions from Search Query Performance and Ads data. Suggestions never create campaigns or keywords directly.</p></div><form><select name="action" defaultValue={action} className="rounded border px-2 py-1 text-sm">{ACTIONS.map(a => <option key={a}>{a}</option>)}</select><button className="ml-2 rounded bg-slate-900 px-3 py-1 text-sm text-white">Filter</button></form><div className="overflow-x-auto rounded border bg-white"><table className="w-full text-sm"><thead><tr className="border-b text-left text-xs uppercase text-slate-500"><th className="p-3">Score / query</th><th className="p-3 num">Volume</th><th className="p-3 num">CTR / CVR</th><th className="p-3 num">Ads</th><th className="p-3">Suggested action</th></tr></thead><tbody>{rows.map(r => <tr key={`${r.asin}:${r.search_query}`} className="border-b"><td className="p-3"><b>{r.sqp_opportunity_score}</b> · {r.search_query}<div className="text-xs text-slate-500">{r.asin}{r.exists_as_exact ? " · exact exists" : " · not exact"}</div></td><td className="p-3 num">{count(r.query_volume_30d)}</td><td className="p-3 num">{percent(r.query_ctr)} / {percent(r.query_cvr)}</td><td className="p-3 num">{money(r.ad_spend_30d)}<div className="text-xs text-slate-500">ACOS {percent(r.ads_acos)}</div></td><td className="p-3"><span className="rounded bg-slate-100 px-2 py-1 font-mono text-xs">{r.suggested_action}</span>{r.economics_incomplete && <div className="mt-1 text-xs tone-warn">economics missing</div>}</td></tr>)}</tbody></table></div></div>
}
