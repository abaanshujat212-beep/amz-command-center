import Link from "next/link"
import { notFound } from "next/navigation"
import { approveAction, rejectAction } from "@/app/approvals/actions"
import { withTenant } from "@/lib/db"
import { recommendationDetail, RecommendationQueryError } from "@/lib/recommendations"
import { canApprove, currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"
const pretty = (value: string | null) => (value ?? "not recorded").replaceAll("_", " ")
const json = (value: unknown) => value == null ? "Not recorded" : JSON.stringify(value, null, 2)

export default async function RecommendationDetail({ params }: { params: Promise<{ id: string }> }) {
	const { id } = await params
	const tenantId = await currentTenantId()
	let item: Awaited<ReturnType<typeof recommendationDetail>>
	try { item = await withTenant(tenantId, client => recommendationDetail(client, tenantId, id)) }
	catch (error) { if (error instanceof RecommendationQueryError && error.status === 404) notFound(); throw error }
	const armed = await canApprove()
	const capability = item.capability
	const liveSupported = capability.approval_supported && capability.live_baseline_read_supported && capability.live_apply_supported && capability.rollback_supported && capability.verification_supported && !capability.local_only
	const pending = item.status === "pending"
	return <div className="space-y-5">
		<Link href="/recommendations" className="text-sm text-slate-600">← Recommendation Center</Link>
		<div className="rounded-lg border border-slate-200 bg-white p-5"><div className="flex flex-wrap justify-between gap-4"><div><p className="text-xs uppercase tracking-wide text-slate-500">{pretty(item.recommendation_type)}</p><h1 className="mt-1 text-xl font-semibold">{item.action_type}</h1><p className="mt-1 text-sm text-slate-600">{item.entity_type} · {item.entity_id}</p></div><div className="text-right text-sm"><p className="capitalize">{item.status} · {pretty(item.risk)} risk</p><p className="mt-1 text-slate-500">{Math.round((item.confidence ?? 0) * 100)}% confidence · {item.lookback_days ?? "—"} day lookback</p></div></div>
			<div className="mt-5 grid gap-3 md:grid-cols-2"><Panel title="Current value" content={json(item.before_value)} /><Panel title="Proposed value" content={json(item.after_value)} /></div>
			<h2 className="mt-5 text-sm font-semibold">Why this is recommended</h2><p className="mt-1 text-sm text-slate-700">{item.reason_text ?? "No rationale was recorded."}</p>{item.clamped && <p className="mt-2 text-xs text-amber-700">Guardrail adjusted this proposal: {item.clamp_note ?? "limit applied"}</p>}
		</div>
		<div className="grid gap-4 lg:grid-cols-2"><Panel title="Goals and objective" content={json(item.objective_snapshot)} /><Panel title="Strategy context" content={json(item.strategy_snapshot)} /><Panel title="Expected behavior" content={json(item.expected_behavior)} /><Panel title="Economics" content={json(item.economic_effect)} /></div>
		<div className={`rounded-lg border p-4 ${liveSupported ? "border-emerald-300 bg-emerald-50" : "border-amber-300 bg-amber-50"}`}><h2 className="font-semibold">Amazon execution capability</h2><p className="mt-1 text-sm">{liveSupported ? "The capability registry has a complete live lifecycle. Approval remains subject to tenant readiness, authorized evidence, collision checks, and live drift protection." : "Unsupported for live application. This remains recommendation-only because the capability registry does not declare the complete baseline-read, apply, rollback, and verification lifecycle."}</p></div>
		<div className="rounded-lg border border-slate-200 bg-white p-4"><h2 className="font-semibold">Conflicts and dependencies</h2><p className="mt-2 text-sm">{item.dependencyState.blockedBy ? `Blocked by: ${item.dependencyState.blockedBy}` : "No optimizer dependency blocker was recorded. Collision checks still run at approval time."}</p></div>
		<div className="rounded-lg border border-slate-200 bg-white p-4"><h2 className="font-semibold">Evidence</h2>{item.evidence.length === 0 ? <p className="mt-2 text-sm text-slate-600">No evidence records were attached.</p> : <ul className="mt-3 space-y-3">{item.evidence.map((evidence, index) => <li key={`${evidence.source_ref}-${index}`} className="rounded border border-slate-200 p-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><strong>{pretty(evidence.evidence_kind)}</strong><span className="text-slate-500">{evidence.completeness}</span></div><p className="mt-1 text-slate-600">{evidence.source_type} · {evidence.source_ref}</p><pre className="mt-2 overflow-auto whitespace-pre-wrap text-xs">{json(evidence.detail)}</pre></li>)}</ul>}</div>
		{pending && <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-4"><form action={approveAction}><input type="hidden" name="id" value={item.id}/><button disabled={!armed || !liveSupported || Boolean(item.dependencyState.blockedBy)} className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:bg-slate-300">Approve through existing workflow</button></form><form action={rejectAction}><input type="hidden" name="id" value={item.id}/><button disabled={!armed} className="rounded border border-slate-300 px-4 py-2 text-sm disabled:text-slate-400">Reject</button></form>{!armed && <span className="text-xs text-amber-700">Owner or Admin role required.</span>}</div>}
	</div>
}

function Panel({ title, content }: { title: string; content: string }) { return <section className="rounded-lg border border-slate-200 bg-white p-4"><h2 className="text-sm font-semibold">{title}</h2><pre className="mt-2 overflow-auto whitespace-pre-wrap break-words text-xs text-slate-700">{content}</pre></section> }
