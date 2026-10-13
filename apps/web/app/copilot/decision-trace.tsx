"use client"

import { useState } from "react"

type Evidence = { id: string; kind: string; event: string; at: string; detail: Record<string, unknown> }
type Trace = { id: string; narrative: string; evidence: Evidence[]; noWrite: true }

export function DecisionTrace({ initialActionId = "" }: { initialActionId?: string }) {
	const [actionId, setActionId] = useState(initialActionId)
	const [trace, setTrace] = useState<Trace | null>(null)
	const [comment, setComment] = useState("")
	const [message, setMessage] = useState("")
	const [busy, setBusy] = useState(false)
	async function explain() {
		setBusy(true); setMessage(""); setTrace(null)
		const response = await fetch("/api/copilot/explain", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ actionId }) })
		const json = await response.json()
		if (response.ok) setTrace(json); else setMessage(json.error ?? "Decision trace failed.")
		setBusy(false)
	}
	async function feedback(value: "helpful" | "not_helpful" | "request_review") {
		if (!trace) return
		setBusy(true); setMessage("")
		const response = await fetch("/api/copilot/feedback", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ explanationId: trace.id, feedback: value, comment }) })
		const json = await response.json()
		setMessage(response.ok ? `Feedback saved as ${json.status}. No setting or Amazon action was changed.` : (json.error ?? "Feedback failed."))
		setBusy(false)
	}
	return <section className="rounded-lg border bg-white p-4">
		<div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="font-medium">Decision Trace</h2><p className="mt-1 text-sm text-slate-600">Explain an action from immutable rule and execution events. Source content is treated as data, never as instructions.</p></div><span className="rounded bg-green-100 px-2 py-1 text-xs font-medium text-green-800">read-only evidence</span></div>
		<div className="mt-4 flex gap-2"><input aria-label="Action ID" value={actionId} onChange={event => setActionId(event.target.value)} placeholder="Action UUID" className="min-w-0 flex-1 rounded border px-3 py-2 font-mono text-sm"/><button type="button" disabled={busy || !actionId.trim()} onClick={explain} className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:bg-slate-300">Explain</button></div>
		{message && <p role="status" className="mt-3 rounded border border-blue-100 bg-blue-50 p-2 text-sm text-blue-900">{message}</p>}
		{trace && <div className="mt-4 space-y-3"><p className="rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800">{trace.narrative}</p><ol className="space-y-2">{trace.evidence.map((item, index) => <li key={item.id} className="rounded border p-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><b>{index + 1}. {item.event}</b><span className="text-xs text-slate-500">{item.kind} · {new Date(item.at).toLocaleString()}</span></div><pre className="mt-2 overflow-auto whitespace-pre-wrap text-xs text-slate-600">{JSON.stringify(item.detail, null, 2)}</pre><div className="mt-1 font-mono text-[11px] text-slate-400">evidence {item.id}</div></li>)}</ol><div className="rounded border border-amber-200 bg-amber-50 p-3"><p className="text-xs text-amber-900">Feedback creates a review proposal only. It cannot change this decision, settings, an action, or Amazon.</p><textarea value={comment} onChange={event => setComment(event.target.value)} maxLength={2000} rows={2} placeholder="Optional note; required for review request" className="mt-2 w-full rounded border bg-white px-3 py-2 text-sm"/><div className="mt-2 flex flex-wrap gap-2"><button type="button" disabled={busy} onClick={() => feedback("helpful")} className="rounded border bg-white px-3 py-1.5 text-xs">Helpful</button><button type="button" disabled={busy} onClick={() => feedback("not_helpful")} className="rounded border bg-white px-3 py-1.5 text-xs">Not helpful</button><button type="button" disabled={busy || !comment.trim()} onClick={() => feedback("request_review")} className="rounded bg-amber-900 px-3 py-1.5 text-xs text-white disabled:bg-amber-300">Request human review</button></div></div></div>}
	</section>
}
