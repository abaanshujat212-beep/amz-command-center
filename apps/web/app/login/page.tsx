"use client"

import { useSearchParams, useRouter } from "next/navigation"
import { FormEvent, useState } from "react"
import { authClient } from "@/lib/auth-client"

type Membership = { tenant_id: string; name: string; slug: string; role: string }

export default function LoginPage() {
	const params = useSearchParams()
	const router = useRouter()
	const [error, setError] = useState("")
	const [busy, setBusy] = useState(false)
	const [memberships, setMemberships] = useState<Membership[]>([])
	const [selectedTenant, setSelectedTenant] = useState("")
	const next = params.get("next")?.startsWith("/") ? params.get("next")! : "/"

	async function selectTenant(tenantId: string) {
		const selected = await fetch("/api/tenant/select", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ tenantId }) })
		if (!selected.ok) { const data = await selected.json(); setError(data.error ?? "Tenant selection failed."); setBusy(false); return }
		router.push(next); router.refresh()
	}

	async function submit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault(); setBusy(true); setError("")
		const form = new FormData(event.currentTarget)
		const result = await authClient.signIn.email({ email: String(form.get("email")), password: String(form.get("password")) })
		if (result.error) { setError(result.error.message ?? "Sign in failed."); setBusy(false); return }
		const response = await fetch("/api/tenant/memberships")
		if (!response.ok) { await authClient.signOut(); setError("No tenant memberships found for this user."); setBusy(false); return }
		const data = await response.json() as { memberships: Membership[] }
		if (data.memberships.length === 0) { await authClient.signOut(); setError("No client account is assigned to this login."); setBusy(false); return }
		if (data.memberships.length === 1) { await selectTenant(data.memberships[0].tenant_id); return }
		setMemberships(data.memberships); setSelectedTenant(data.memberships[0].tenant_id); setBusy(false)
	}

	async function continueTenant() { if (!selectedTenant) return; setBusy(true); await selectTenant(selectedTenant) }

	return <main className="mx-auto flex min-h-screen max-w-md items-center px-6"><div className="w-full space-y-4 rounded-xl border bg-white p-8 shadow-sm"><div><div className="text-xs font-semibold tracking-widest text-blue-700">AXATY</div><h1 className="mt-2 text-2xl font-semibold">Command Center login</h1><p className="mt-1 text-sm text-slate-600">Sign in with email/password. If this login belongs to multiple clients, choose the client after authentication.</p></div>{memberships.length === 0 ? <form onSubmit={submit} className="space-y-4"><label className="block text-sm font-medium">Email<input required name="email" type="email" autoComplete="email" className="mt-1 w-full rounded border px-3 py-2" /></label><label className="block text-sm font-medium">Password<input required name="password" type="password" autoComplete="current-password" className="mt-1 w-full rounded border px-3 py-2" /></label>{error && <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}<button disabled={busy} className="w-full rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50">{busy ? "Signing in…" : "Sign in"}</button><p className="text-xs text-slate-500">Tenant ID is no longer required at login. Access comes from tenant membership.</p></form> : <div className="space-y-4"><div className="rounded bg-blue-50 p-3 text-sm text-blue-800">This login has access to multiple client accounts. Choose where to enter.</div><div className="space-y-2">{memberships.map(m => <label key={m.tenant_id} className="flex cursor-pointer gap-3 rounded border p-3 text-sm hover:bg-slate-50"><input type="radio" name="tenant" value={m.tenant_id} checked={selectedTenant === m.tenant_id} onChange={() => setSelectedTenant(m.tenant_id)}/><span><b>{m.name}</b><span className="ml-2 text-xs text-slate-500">{m.slug} · {m.role}</span></span></label>)}</div>{error && <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}<button onClick={continueTenant} disabled={busy || !selectedTenant} className="w-full rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50">{busy ? "Opening…" : "Open selected client"}</button></div>}</div></main>
}
