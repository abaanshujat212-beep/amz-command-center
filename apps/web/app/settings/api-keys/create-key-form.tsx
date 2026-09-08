"use client"

import { useState, useTransition } from "react"
import { API_SCOPES, scopeDescription } from "@/lib/api-scopes"
import { createApiKey } from "./actions"

export function CreateKeyForm() {
	const [token, setToken] = useState<string | null>(null)
	const [selected, setSelected] = useState<string[]>(["read"])
	const [pending, startTransition] = useTransition()
	const sensitive = selected.some(scope => scope === "approve" || scope === "write")
	function toggle(scope: string, checked: boolean) { setSelected(current => checked ? Array.from(new Set([...current, scope])) : current.filter(item => item !== scope)) }
	return <div className="rounded border bg-white p-4"><h2 className="font-medium">Create platform API key</h2><p className="mt-1 text-sm text-slate-600">Keys are shown once. Store them in your client secret manager; only a hash is saved.</p>{token && <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm"><div className="font-medium text-amber-900">Copy this key now</div><code className="mt-2 block break-all rounded bg-white p-2 text-xs">{token}</code></div>}{sensitive && <div className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800"><b>Sensitive scopes selected.</b> Approval/write-capable clients must follow RBAC, confirmation, idempotency and audit rules. Write tools remain route-gated and should not directly mutate Amazon.</div>}<form className="mt-4 grid gap-3" action={(form) => startTransition(async () => setToken((await createApiKey(form)).token))}><input name="name" required minLength={2} maxLength={80} placeholder="Key name" className="rounded border px-3 py-2 text-sm"/><div className="grid gap-2 sm:grid-cols-3">{API_SCOPES.map(scope => <label key={scope} className={scope === "write" ? "rounded border border-red-200 bg-red-50 p-3 text-sm" : "rounded border bg-slate-50 p-3 text-sm"}><span className="flex items-center gap-2 font-medium"><input type="checkbox" name="scope" value={scope} defaultChecked={scope === "read"} onChange={e => toggle(scope, e.currentTarget.checked)}/>{scope}</span><span className="mt-1 block text-xs text-slate-600">{scopeDescription(scope)}</span></label>)}</div><button disabled={pending} className="w-fit rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:bg-slate-300">{pending ? "Creating…" : "Create key"}</button></form></div>
}
