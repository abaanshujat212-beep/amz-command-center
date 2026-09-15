"use client"

import { useRouter } from "next/navigation"
import { useState } from "react"

export function PortfolioOpenAccount({ tenantId, workspaceId, returnTo = "/" }: { tenantId: string; workspaceId: string; returnTo?: string }) {
	const router = useRouter()
	const [busy, setBusy] = useState(false)
	const [error, setError] = useState("")
	async function openAccount() {
		setBusy(true)
		setError("")
		const response = await fetch("/api/tenant/select", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify({ tenantId, workspaceId, returnTo }),
		})
		const result = await response.json()
		if (!response.ok) {
			setError(result.error ?? "Account access is no longer authorized.")
			setBusy(false)
			return
		}
		router.push(result.returnTo)
		router.refresh()
	}
	return <span className="inline-flex flex-col items-end gap-1"><button type="button" disabled={busy} onClick={openAccount} className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">{busy ? "Opening…" : "Open account"}</button>{error && <span role="alert" className="max-w-48 text-right text-xs text-red-700">{error}</span>}</span>
}
