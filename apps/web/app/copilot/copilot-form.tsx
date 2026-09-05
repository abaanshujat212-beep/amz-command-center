"use client"

import { useState } from "react"
import { COPILOT_QUESTIONS } from "@/lib/copilot-benchmarks"
import type { CopilotResult } from "@/lib/copilot-execution"

export function CopilotForm() {
	const [question, setQuestion] = useState("")
	const [result, setResult] = useState<CopilotResult | null>(null)
	const [busy, setBusy] = useState(false)
	async function run() {
		setBusy(true)
		setResult(null)
		const res = await fetch("/api/copilot", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question }) })
		const json = await res.json()
		setResult(res.ok ? json : { ok: false, question, tier: "T1", answer: json.error ?? "Copilot request failed", notes: [] })
		setBusy(false)
	}
	return <section className="rounded-lg border bg-white p-4"><h2 className="font-medium">Ask a question</h2><p className="mt-1 text-sm text-slate-600">Questions now enter through the tenant-authenticated copilot API boundary. T2/write-like prompts are accepted as proposals only and cannot apply changes.</p><div className="mt-4 grid gap-3"><textarea value={question} onChange={e => setQuestion(e.target.value)} rows={4} placeholder="Example: Kaun se keywords ne paisa jalaya magar order nahi diya?" className="rounded border px-3 py-2 text-sm"/><div className="flex flex-wrap gap-2"><button type="button" disabled={busy || !question.trim()} onClick={run} className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:bg-slate-300">{busy ? "Checking…" : "Run through copilot boundary"}</button>{COPILOT_QUESTIONS.slice(0,3).map(q => <button type="button" key={q.key} onClick={() => setQuestion(q.questionUr)} className="rounded border px-3 py-2 text-xs text-slate-600 hover:bg-slate-50">{q.intent}</button>)}</div></div>{result && <div className={result.tier === "T2" ? "mt-4 rounded border border-amber-200 bg-amber-50 p-3" : "mt-4 rounded border border-green-200 bg-green-50 p-3"}><div className="text-xs font-semibold uppercase tracking-wide">{result.tier} · {result.tier === "T2" ? "proposal only" : "read-only"}</div><p className="mt-1 text-sm">{result.answer}</p>{result.notes.length > 0 && <p className="mt-2 text-xs text-slate-600">{result.notes.join(" · ")}</p>}</div>}</section>
}
