"use client"

import { useState } from "react"
import { COPILOT_QUESTIONS } from "@/lib/copilot-benchmarks"
import type { CopilotResult } from "@/lib/copilot-execution"

type SpeechRecognitionLike = { lang: string; interimResults: boolean; start: () => void; onresult: ((event: { results: ArrayLike<{ 0: { transcript: string } }> }) => void) | null; onend: (() => void) | null; onerror: (() => void) | null }
type SpeechWindow = Window & { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike }

function errorResult(question: string, answer: string, source: "text" | "voice"): CopilotResult {
	return { ok: false, question, tier: "T1", answer, notes: [], requiresConfirmation: false, source, runnerMode: "contract" }
}

export function CopilotForm() {
	const [question, setQuestion] = useState("")
	const [result, setResult] = useState<CopilotResult | null>(null)
	const [busy, setBusy] = useState(false)
	const [listening, setListening] = useState(false)
	const [source, setSource] = useState<"text" | "voice">("text")
	async function run(inputSource: "text" | "voice" = source) {
		setBusy(true)
		setResult(null)
		const res = await fetch("/api/copilot", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question, source: inputSource }) })
		const json = await res.json()
		setResult(res.ok ? json : errorResult(question, json.error ?? "Copilot request failed", inputSource))
		setBusy(false)
	}
	function startVoice() {
		const w = window as SpeechWindow
		const Recognition = w.SpeechRecognition ?? w.webkitSpeechRecognition
		if (!Recognition) { setResult(errorResult(question, "This browser does not expose speech recognition. Type the Urdu/English command instead.", "voice")); return }
		const rec = new Recognition()
		rec.lang = "ur-PK"
		rec.interimResults = false
		rec.onresult = (event) => { const transcript = event.results[0]?.[0]?.transcript ?? ""; setQuestion(transcript); setSource("voice") }
		rec.onerror = () => setListening(false)
		rec.onend = () => setListening(false)
		setListening(true)
		rec.start()
	}
	return <section className="rounded-lg border bg-white p-4"><h2 className="font-medium">Ask or speak a command</h2><p className="mt-1 text-sm text-slate-600">Urdu/English text and browser voice transcripts enter through the tenant-authenticated copilot API boundary. T2/write-like prompts require confirmation and cannot apply changes.</p><div className="mt-4 grid gap-3"><textarea value={question} onChange={e => { setQuestion(e.target.value); setSource("text") }} rows={4} placeholder="Example: Kaun se keywords ne paisa jalaya magar order nahi diya?" className="rounded border px-3 py-2 text-sm"/><div className="flex flex-wrap gap-2"><button type="button" disabled={busy || !question.trim()} onClick={() => run()} className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:bg-slate-300">{busy ? "Checking…" : "Run through copilot boundary"}</button><button type="button" onClick={startVoice} className={listening ? "rounded bg-red-600 px-4 py-2 text-sm text-white" : "rounded border px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"}>{listening ? "Listening…" : "Speak Urdu/English"}</button>{COPILOT_QUESTIONS.slice(0,3).map(q => <button type="button" key={q.key} onClick={() => { setQuestion(q.questionUr); setSource("text") }} className="rounded border px-3 py-2 text-xs text-slate-600 hover:bg-slate-50">{q.intent}</button>)}</div></div>{source === "voice" && <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">Voice transcript captured. Review the text before running — numeric/write-like commands still need confirmation.</div>}{result && <div className={result.tier === "T2" ? "mt-4 rounded border border-amber-200 bg-amber-50 p-3" : "mt-4 rounded border border-green-200 bg-green-50 p-3"}><div className="text-xs font-semibold uppercase tracking-wide">{result.tier} · {result.tier === "T2" ? "proposal only" : "read-only"} · {result.source}</div><p className="mt-1 text-sm">{result.answer}</p>{result.requiresConfirmation && <div className="mt-2 rounded bg-white/70 p-2 text-xs font-medium text-amber-900">Confirmation required before any numeric or write-like action can move forward.</div>}{result.notes.length > 0 && <p className="mt-2 text-xs text-slate-600">{result.notes.join(" · ")}</p>}</div>}</section>
}
