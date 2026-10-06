import { withTenant } from "@/lib/db"
import { stamp } from "@/lib/format"
import { listResearchCandidates } from "@/lib/research"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export default async function ResearchPage() {
	const actor = await currentContext()
	const rows = await withTenant(actor.tenantId, c => listResearchCandidates(c, actor.tenantId))
	return <div className="space-y-5">
		<div><h1 className="text-lg font-semibold">Product research</h1><p className="text-sm text-slate-600">Durable research projects kept separate from your current Amazon catalog. Market facts must include provider, observation time, method, scope and completeness.</p></div>
		<div className="grid gap-3 sm:grid-cols-4"><div className="rounded-lg border bg-white p-4"><div className="text-xs uppercase text-slate-500">Candidates</div><div className="mt-1 text-2xl font-semibold">{rows.length}</div></div>{["watchlist", "shortlisted", "blocked"].map(state => <div key={state} className="rounded-lg border bg-white p-4"><div className="text-xs uppercase text-slate-500">{state}</div><div className="mt-1 text-2xl font-semibold">{state === "blocked" ? rows.filter(r => r.blocked_count > 0).length : rows.filter(r => r.status === state).length}</div></div>)}</div>
		<div className="overflow-x-auto rounded-lg border bg-white"><table className="w-full text-sm"><thead><tr className="border-b text-left text-xs uppercase text-slate-500"><th className="p-3">Candidate</th><th className="p-3">Project / scope</th><th className="p-3">Evidence</th><th className="p-3">State</th></tr></thead><tbody>{rows.map(row => <tr key={row.id} className="border-b align-top"><td className="p-3 font-medium">{row.title}<div className="text-xs font-normal text-slate-500">{row.asin ?? "No ASIN"}{row.sku ? ` · ${row.sku}` : ""}</div></td><td className="p-3">{row.project_name}<div className="text-xs text-slate-500">{row.candidate_kind === "own_catalog" ? "Own catalog" : "Market research"}</div></td><td className="p-3">{row.observation_count} observations<div className="text-xs text-slate-500">{row.complete_count} complete · {row.partial_count} partial · {row.blocked_count} blocked</div><div className="text-xs text-slate-400">Latest {stamp(row.latest_observed_at)}</div></td><td className="p-3"><span className="rounded bg-slate-100 px-2 py-1 text-xs">{row.status}</span></td></tr>)}</tbody></table></div>
		{rows.length === 0 && <div className="rounded-lg border border-dashed bg-white p-8 text-sm text-slate-600"><b>No research candidates yet.</b><p className="mt-1">Create a research project through the tenant-scoped API. This workspace never converts missing licensed market data into fake opportunity rows.</p></div>}
	</div>
}
