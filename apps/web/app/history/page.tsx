import Link from "next/link"
import { isMoneyAction, shown } from "@/lib/action-value"
import { withTenant } from "@/lib/db"
import { money, stamp } from "@/lib/format"
import { openAlerts, recentPipelineRuns } from "@/lib/queries"
import { actionHistory, historyTotals, type HistoryRow } from "@/lib/queries-drilldown"
import { ALLOWED_WINDOWS, parseDays, windowHref, type Window } from "@/lib/range"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

function statusTone(status: string): string {
	if (status === "applied" || status === "verified" || status === "success") return "tone-good"
	if (status === "failed" || status === "rolled_back" || status === "partial" || status === "critical") return "tone-bad"
	if (status === "approved" || status === "running" || status === "warning") return "tone-warn"
	return "tone-unknown"
}

function Side({ raw, type }: { raw: unknown; type: string }) {
	const text = shown(raw)
	if (text === null) return <span className="text-slate-400">unknown</span>
	const n = Number(text)
	if (isMoneyAction(type) && Number.isFinite(n)) return <>{money(n)}</>
	return <>{text}</>
}

function WindowPicker({ days }: { days: Window }) {
	return <div className="flex gap-1 text-xs">{ALLOWED_WINDOWS.map((d) => <Link key={d} href={windowHref("/history", d)} className={d === days ? "rounded bg-slate-900 px-2 py-1 text-white" : "rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-100"}>{d}d</Link>)}</div>
}

function Outcome({ row }: { row: HistoryRow }) {
	if (row.status === "failed" && row.error) {
		const drift = row.error.startsWith("drift:")
		return <div className="text-xs"><span className={drift ? "text-warn" : "text-bad"}>{drift ? "refused: value had drifted" : "failed"}</span><div className="text-slate-500">{row.error}</div></div>
	}
	if (row.outcome) return <span className="text-xs text-slate-600">{row.outcome}</span>
	if (row.status === "applied") return <span className="text-xs text-slate-500" title="Verified 7 days after apply">awaiting verification</span>
	return <span className="text-xs text-slate-400">&mdash;</span>
}

export default async function History({ searchParams }: { searchParams: Promise<{ days?: string }> }) {
	const sp = await searchParams
	const days = parseDays(sp.days)
	const tenantId = await currentTenantId()
	const { rows, totals, alerts, runs } = await withTenant(tenantId, async (c) => ({
		rows: await actionHistory(c, days, 200),
		totals: await historyTotals(c, days),
		alerts: await openAlerts(c, 10),
		runs: await recentPipelineRuns(c, 12),
	}))
	const appliedSpend = totals.filter((t) => t.spend_delta !== null).reduce((sum, t) => sum + Number(t.spend_delta ?? 0), 0)
	return <div className="space-y-6">
		<div className="flex flex-wrap items-baseline justify-between gap-3"><h1 className="text-lg font-semibold">Run history & decisions</h1><WindowPicker days={days} /></div>
		<section className="grid gap-4 lg:grid-cols-2">
			<div className="rounded-lg border border-slate-200 bg-white p-4">
				<div className="mb-3 flex items-center justify-between"><h2 className="font-medium">Open alerts</h2><span className="text-xs text-slate-500">{alerts.length} open</span></div>
				{alerts.length === 0 ? <p className="text-sm text-slate-500">No open alerts.</p> : <div className="space-y-2">{alerts.map((a) => <div key={a.id} className="rounded border border-slate-100 p-2 text-sm"><div className={`font-medium ${statusTone(a.severity)}`}>{a.severity}: {a.title}</div><div className="text-xs text-slate-500">{a.kind}{a.entity_ref ? ` · ${a.entity_ref}` : ""} · {stamp(a.created_at)}</div></div>)}</div>}
			</div>
			<div className="rounded-lg border border-slate-200 bg-white p-4">
				<div className="mb-3 flex items-center justify-between"><h2 className="font-medium">Recent pipeline runs</h2><span className="text-xs text-slate-500">latest {runs.length}</span></div>
				{runs.length === 0 ? <p className="text-sm text-slate-500">No pipeline runs yet.</p> : <div className="space-y-2">{runs.map((r, i) => <div key={`${r.dataset}-${r.started_at}-${i}`} className="grid grid-cols-[1fr_auto] gap-2 rounded border border-slate-100 p-2 text-sm"><div><div className="font-medium">{r.dataset}</div><div className="text-xs text-slate-500">{stamp(r.started_at)}{r.finished_at ? ` → ${stamp(r.finished_at)}` : ""}</div>{r.error && <div className="text-xs text-bad">{r.error}</div>}</div><div className={`text-xs ${statusTone(r.status)}`}>{r.status}<div className="text-right text-slate-500">{r.rows_loaded ?? 0} rows</div></div></div>)}</div>}
			</div>
		</section>
		<div className="flex flex-wrap gap-2 text-xs">{totals.length === 0 ? <span className="text-slate-500">Nothing decided in this window.</span> : totals.map((t) => <span key={t.status} className={`rounded border border-slate-200 bg-white px-2 py-1 ${statusTone(t.status)}`}>{t.status} <span className="tabular-nums">{t.n}</span></span>)}{appliedSpend !== 0 && <span className="rounded border border-slate-200 bg-white px-2 py-1">applied bid/budget delta <span className="tabular-nums">{money(appliedSpend)}</span></span>}</div>
		{rows.length === 0 ? <div className="rounded-lg border border-slate-200 bg-white p-8 text-sm text-slate-600"><p>No decisions in the last {days} days.</p><Link href="/approvals" className="mt-3 inline-block text-blue-700 hover:underline">Open the approval queue &rarr;</Link></div> : <table className="w-full border-collapse bg-white text-sm"><thead><tr className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500"><th className="px-3 py-2">Decided</th><th className="px-3 py-2">Change</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Applied</th><th className="px-3 py-2">Result</th><th className="px-3 py-2">Rule</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id} className="border-b border-slate-100 align-top"><td className="px-3 py-2 whitespace-nowrap"><div>{stamp(row.decided_at ?? row.sort_at)}</div>{row.decided_at === null && <div className="text-xs text-slate-400">proposed</div>}</td><td className="px-3 py-2"><div className="font-medium">{row.action_type}</div><div className="text-xs text-slate-500">{row.entity_type} {row.entity_id}</div><div className="mt-1 tabular-nums"><Side raw={row.before_value} type={row.action_type} /><span className="mx-2 text-slate-400">&rarr;</span><span className="font-medium"><Side raw={row.after_value} type={row.action_type} /></span></div></td><td className={`px-3 py-2 ${statusTone(row.status)}`}>{row.status}{row.decision !== null && row.decision !== row.status && <div className="text-xs text-slate-500">decided: {row.decision}</div>}</td><td className="px-3 py-2 whitespace-nowrap text-xs text-slate-600">{row.applied_at ? stamp(row.applied_at) : "\u2014"}{row.rolled_back_at && <div className="text-bad">rolled back {stamp(row.rolled_back_at)}</div>}</td><td className="px-3 py-2"><Outcome row={row} /></td><td className="px-3 py-2 text-xs text-slate-500">{row.rule_name ?? row.rule_code ?? "manual"}{row.reason_text && <div className="text-slate-600">{row.reason_text}</div>}</td></tr>)}</tbody></table>}
	</div>
}
