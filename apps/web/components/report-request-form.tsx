"use client"

import { useRouter } from "next/navigation"
import { useState, type FormEvent } from "react"

export function ReportRequestForm({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
	const router = useRouter()
	const [message, setMessage] = useState("")
	const [busy, setBusy] = useState(false)
	async function submit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault(); setBusy(true); setMessage("")
		const data = new FormData(event.currentTarget)
		const response = await fetch("/api/reports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
			dateFrom: data.get("dateFrom"), dateTo: data.get("dateTo"), outputFormat: data.get("outputFormat"),
			filters: data.get("marketplace") ? { marketplace: data.get("marketplace") } : {}, idempotencyKey: crypto.randomUUID(),
		}) })
		const result = await response.json().catch(() => ({}))
		setBusy(false)
		if (!response.ok) { setMessage(result.error ?? "Report request failed."); return }
		setMessage("Report queued."); router.refresh()
	}
	return <form onSubmit={submit} className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-5">
		<label className="text-xs text-slate-600">From<input required name="dateFrom" type="date" defaultValue={dateFrom} className="mt-1 w-full rounded border px-2 py-2 text-sm" /></label>
		<label className="text-xs text-slate-600">To<input required name="dateTo" type="date" defaultValue={dateTo} className="mt-1 w-full rounded border px-2 py-2 text-sm" /></label>
		<label className="text-xs text-slate-600">Format<select name="outputFormat" className="mt-1 w-full rounded border px-2 py-2 text-sm"><option value="csv">CSV</option><option value="xlsx">XLSX</option><option value="pdf">PDF</option></select></label>
		<label className="text-xs text-slate-600">Marketplace<input name="marketplace" placeholder="optional" className="mt-1 w-full rounded border px-2 py-2 text-sm" /></label>
		<div className="flex items-end gap-2"><button disabled={busy} className="rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:bg-slate-300">{busy ? "Queuing…" : "Create report"}</button></div>
		{message && <p role="status" className="text-sm sm:col-span-2 lg:col-span-5">{message}</p>}
	</form>
}
