"use client"

import { useRouter } from "next/navigation"
import { useState } from "react"

export function ReportRetryButton({ id }: { id: string }) {
	const router = useRouter(); const [busy, setBusy] = useState(false); const [error, setError] = useState("")
	async function retry() {
		setBusy(true); setError("")
		const response = await fetch(`/api/reports/${id}/retry`, { method: "POST" })
		const result = await response.json().catch(() => ({})); setBusy(false)
		if (!response.ok) { setError(result.error ?? "Retry failed."); return }
		router.refresh()
	}
	return <span><button type="button" onClick={retry} disabled={busy} className="rounded border px-2 py-1 text-xs disabled:text-slate-400">{busy ? "Retrying…" : "Retry"}</button>{error && <span role="alert" className="ml-2 text-xs text-red-700">{error}</span>}</span>
}
