import { isMoneyAction, shown } from "@/lib/action-value"
import { withTenant } from "@/lib/db"
import { money, percent, stamp } from "@/lib/format"
import { verificationScorecards } from "@/lib/queries-verification"
import type { VerificationScorecard } from "@/lib/queries-verification"
import { currentContext } from "@/lib/session"
import { ActionExperiments } from "@/components/action-experiments"

export const dynamic = "force-dynamic"

type WindowMetrics = { cost?: number; sales?: number; clicks?: number; orders?: number; acos?: number | null; cvr?: number | null }
type Impact = { before?: WindowMetrics; after?: WindowMetrics; entity_type?: string }

function Value({ raw, type }: { raw: unknown; type: string }) { const text = shown(raw); if (text === null) return <span className="text-slate-400">unknown</span>; const n = Number(text); if (isMoneyAction(type) && Number.isFinite(n)) return <>{money(n)}</>; return <>{text}</> }
function metricNumber(value: unknown): number | null { const n = Number(value); return Number.isFinite(n) ? n : null }
function impact(raw: unknown): Impact { return raw && typeof raw === "object" ? raw as Impact : {} }
function outcomeTone(outcome: string | null, status: string): string { if (outcome === "improved") return "tone-good"; if (outcome === "worsened") return "tone-bad"; if (outcome === "neutral") return "tone-warn"; if (status === "applied") return "tone-unknown"; return "tone-warn" }
function MetricBlock({ title, metrics }: { title: string; metrics?: WindowMetrics }) { return <div className="rounded border border-slate-100 bg-slate-50 p-2 text-xs"><div className="mb-1 font-medium text-slate-700">{title}</div><div className="grid grid-cols-2 gap-x-3 gap-y-1"><span>Spend</span><span className="num">{money(metricNumber(metrics?.cost))}</span><span>Sales</span><span className="num">{money(metricNumber(metrics?.sales))}</span><span>Clicks</span><span className="num">{metricNumber(metrics?.clicks) ?? "—"}</span><span>Orders</span><span className="num">{metricNumber(metrics?.orders) ?? "—"}</span><span>ACOS</span><span className="num">{percent(metricNumber(metrics?.acos))}</span><span>CVR</span><span className="num">{percent(metricNumber(metrics?.cvr))}</span></div></div> }

function ConfounderEvidence({ snapshot }: { snapshot: VerificationScorecard["snapshots"][number] }) {
	if (snapshot.confounding_status !== "CONFOUNDED") return null
	return <details className="mt-2 rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">
		<summary className="cursor-pointer font-medium">{snapshot.confounder_count} recorded change{snapshot.confounder_count === 1 ? "" : "s"} overlapped T+{snapshot.horizon_days} measurement windows</summary>
		<p className="mt-2">This horizon is confounded. Its metric movement is descriptive and cannot be attributed to the verified action. Only recorded changes to the same entity are checked; parent-entity and unrecorded changes may be missing.</p>
		<ul className="mt-2 space-y-1">{snapshot.confounders.map((change, index) => <li key={`${change.window}-${change.source}-${change.action_id ?? change.signal_id}-${index}`}>
			<span className="font-medium">{change.window === "baseline" ? "Baseline" : "After"} window</span>
			<span> · {change.source === "amazon_native" ? "Amazon native" : change.source === "manual" ? "Manual" : "AXATY"}</span>
			<span> · {change.change_kind}</span>
			{change.source_ref && <span> · Ref {change.source_ref}</span>}
			<span> · {stamp(change.changed_at)}</span>
		</li>)}</ul>
		{snapshot.evidence_truncated && <p className="mt-2">Showing the 20 most recent recorded changes; {snapshot.confounder_count} overlapped in total.</p>}
	</details>
}

export default async function VerificationPage() {
	const actor = await currentContext()
	const rows = await withTenant(actor.tenantId, c => verificationScorecards(c))
	return <div className="space-y-4">
		<header>
			<h1 className="text-lg font-semibold">Verification scorecards</h1>
			<p className="text-sm text-slate-600">Read-only T+1, T+3, T+7, T+14 and T+30 outcome evidence. Immature settled windows are shown as insufficient data, never as zero performance.</p>
			<p className="mt-1 text-xs text-slate-500">Recorded changes to the same entity are checked against each stored baseline and after window using UTC date boundaries. No recorded overlap does not prove that no other factor changed.</p>
		</header>
		{rows.length === 0 ? <div className="rounded-lg border bg-white p-8 text-sm text-slate-600">No applied or verified actions yet. Snapshots appear as each settled horizon matures.</div> : <div className="space-y-3">
			{rows.map(row => {
				const beforeAfter = impact(row.impact_jsonb)
				const t7 = row.snapshots.find(item => item.horizon_days === 7)
				const t7Confounded = t7?.confounding_status === "CONFOUNDED"
				return <article key={row.id} className="rounded-lg border border-slate-200 bg-white p-4">
					<div className="flex flex-wrap items-start justify-between gap-3">
						<div>
							<div className="font-medium">{row.action_type}<span className="ml-2 text-sm font-normal text-slate-500">{row.entity_type} {row.entity_id}</span></div>
							<div className="mt-1 text-sm tabular-nums"><Value raw={row.before_value} type={row.action_type}/><span className="mx-2 text-slate-400">→</span><span className="font-medium"><Value raw={row.after_value} type={row.action_type}/></span></div>
							<div className="mt-1 text-xs text-slate-500">{row.rule_name ?? row.rule_code ?? "manual"}{row.reason_text ? ` · ${row.reason_text}` : ""}</div>
						</div>
						<div className={`rounded-full px-3 py-1 text-xs font-medium ${t7Confounded ? "bg-amber-100 text-amber-950" : `bg-slate-100 ${outcomeTone(row.outcome, row.status)}`}`}>
							{t7Confounded ? "CONFOUNDED" : row.status === "applied" ? "collecting horizons" : row.outcome ?? "inconclusive"}
						</div>
					</div>
					{t7Confounded && t7?.outcome && <p className="mt-2 text-xs text-amber-900">T+7 observed movement: {t7.outcome}. It is not attributed to this action.</p>}
					<div className="mt-3 flex flex-wrap gap-2">{[1,3,7,14,30].map(day => {
						const snapshot = row.snapshots.find(item => item.horizon_days === day)
						const label = snapshot?.confounding_status === "CONFOUNDED" ? "CONFOUNDED" : snapshot?.status === "COMPLETE" ? snapshot.outcome : snapshot?.status === "INSUFFICIENT_DATA" ? "insufficient data" : snapshot?.status === "FAILED" ? "failed" : "pending"
						return <span key={day} className={`rounded border px-2 py-1 text-xs ${snapshot?.confounding_status === "CONFOUNDED" ? "border-amber-300 bg-amber-50 text-amber-950" : "border-slate-200 bg-slate-50"}`}>T+{day} · {label}</span>
					})}</div>
					{row.snapshots.filter(snapshot => snapshot.confounding_status === "CONFOUNDED").map(snapshot => <ConfounderEvidence key={snapshot.horizon_days} snapshot={snapshot} />)}
					<div className="mt-4 grid gap-3 md:grid-cols-2"><MetricBlock title="Legacy T+7 before" metrics={beforeAfter.before}/><MetricBlock title="Legacy T+7 after" metrics={beforeAfter.after}/></div>
					<div className="mt-3 text-xs text-slate-500">Applied {stamp(row.applied_at)} · T+7 summary {stamp(row.verified_at)}</div>
				</article>
			})}
		</div>}
		<p className="text-xs text-slate-500">Verification is read-only. It never changes Amazon state; it only records whether an approved change improved, worsened, stayed neutral or remained inconclusive.</p>
		<ActionExperiments canManage={actor.role === "owner" || actor.role === "admin"} />
	</div>
}
