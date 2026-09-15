"use client"

import { usePathname, useRouter } from "next/navigation"
import { useEffect, useState } from "react"

type Tenant = { tenant_id: string; name: string; slug: string; role: string }
type Workspace = { workspace_id: string; name: string; slug: string; role: string }
type Options = { tenants: Tenant[]; workspaces: Workspace[] }

export function ContextSwitcher({ currentTenantId, currentWorkspaceId }: { currentTenantId: string; currentWorkspaceId: string | null }) {
	const pathname = usePathname()
	const router = useRouter()
	const [options, setOptions] = useState<Options | null>(null)
	const [tenantId, setTenantId] = useState(currentTenantId)
	const [workspaceId, setWorkspaceId] = useState(currentWorkspaceId ?? "")
	const [error, setError] = useState("")
	const [busy, setBusy] = useState(false)
	useEffect(() => { fetch("/api/context/options").then(r => r.ok ? r.json() : null).then(setOptions).catch(() => setOptions(null)) }, [])
	if (!options || (options.tenants.length <= 1 && options.workspaces.length === 0)) return null
	async function openAccount() {
		setBusy(true); setError("")
		const response = await fetch("/api/tenant/select", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ tenantId, workspaceId: workspaceId || null, returnTo: pathname }) })
		const result = await response.json()
		if (!response.ok) { setError(result.error ?? "Context switch failed."); setBusy(false); return }
		router.push(result.returnTo); router.refresh()
	}
	return <div className="flex flex-wrap items-center gap-2 rounded border bg-white px-2 py-1"><span className="text-[10px] font-semibold tracking-wide text-blue-700">AXATY PORTFOLIO</span><select aria-label="Client account" value={tenantId} onChange={e => setTenantId(e.target.value)} className="max-w-40 rounded border px-2 py-1 text-xs">{options.tenants.map(t => <option key={t.tenant_id} value={t.tenant_id}>{t.name} · {t.role}</option>)}</select>{options.workspaces.length > 0 && <select aria-label="Workspace" value={workspaceId} onChange={e => setWorkspaceId(e.target.value)} className="max-w-36 rounded border px-2 py-1 text-xs"><option value="">Direct account</option>{options.workspaces.map(w => <option key={w.workspace_id} value={w.workspace_id}>{w.name}</option>)}</select>}<button disabled={busy || !tenantId} onClick={openAccount} className="rounded bg-slate-900 px-2 py-1 text-xs text-white disabled:opacity-50">{busy ? "Opening…" : "Open account"}</button>{error && <span role="alert" className="text-xs text-red-700">{error}</span>}</div>
}
