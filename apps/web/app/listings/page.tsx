import { withTenant } from "@/lib/db"
import { listListingProjects } from "@/lib/listings"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export default async function ListingsPage() {
	const actor = await currentContext(); const projects = await withTenant(actor.tenantId, c => listListingProjects(c, actor.tenantId))
	return <div className="space-y-5"><div><h1 className="text-lg font-semibold">Listing Studio</h1><p className="text-sm text-slate-600">Versioned, human-reviewed listing drafts. Nothing on this page writes to Amazon.</p></div>
		<div className="grid gap-3 sm:grid-cols-3"><div className="rounded-lg border bg-white p-4"><div className="text-xs uppercase text-slate-500">Projects</div><div className="mt-1 text-2xl font-semibold">{projects.length}</div></div><div className="rounded-lg border bg-white p-4"><div className="text-xs uppercase text-slate-500">In review</div><div className="mt-1 text-2xl font-semibold">{projects.filter(p => p.review_state === "in_review").length}</div></div><div className="rounded-lg border bg-white p-4"><div className="text-xs uppercase text-slate-500">Approved</div><div className="mt-1 text-2xl font-semibold">{projects.filter(p => p.review_state === "approved").length}</div></div></div>
		{projects.length === 0 ? <div className="rounded-lg border border-dashed bg-white p-8 text-sm text-slate-600">No listing projects yet. Create one through the tenant-scoped Listing Studio API, then add immutable draft versions for review.</div> : <div className="overflow-x-auto rounded-lg border bg-white"><table className="w-full text-sm"><thead><tr className="border-b text-left text-xs uppercase text-slate-500"><th className="p-3">Project</th><th className="p-3">Latest version</th><th className="p-3">Provenance</th><th className="p-3">Review</th></tr></thead><tbody>{projects.map(p => <tr key={p.id} className="border-b"><td className="p-3 font-medium">{p.name}<div className="text-xs font-normal text-slate-500">{p.asin ?? "No ASIN"}{p.sku ? ` · ${p.sku}` : ""} · {p.marketplace}</div></td><td className="p-3">{p.version ? `v${p.version} · ${p.draft_title || "Untitled draft"}` : "No draft"}</td><td className="p-3">{p.origin ?? "—"}<div className="text-xs text-slate-500">{p.review_count} review events</div></td><td className="p-3"><span className="rounded bg-slate-100 px-2 py-1 text-xs">{p.review_state}</span></td></tr>)}</tbody></table></div>}
		<div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><b>Amazon sync is disabled.</b> Approval here records editorial review only and cannot publish a listing.</div>
	</div>
}
