"use client"

import { useSearchParams, useRouter } from "next/navigation"
import { FormEvent, useState } from "react"
import { authClient } from "@/lib/auth-client"

export default function LoginPage() {
	const params = useSearchParams()
	const router = useRouter()
	const [error, setError] = useState("")
	const [busy, setBusy] = useState(false)
	const tenantId = params.get("tenant") ?? ""
	const next = params.get("next")?.startsWith("/") ? params.get("next")! : "/"

	async function submit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault(); setBusy(true); setError("")
		const form = new FormData(event.currentTarget)
		const result = await authClient.signIn.email({ email: String(form.get("email")), password: String(form.get("password")) })
		if (result.error) { setError(result.error.message ?? "Sign in failed."); setBusy(false); return }
		const selected = await fetch("/api/tenant/select", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ tenantId: String(form.get("tenantId")) }) })
		if (!selected.ok) { const data = await selected.json(); await authClient.signOut(); setError(data.error ?? "Tenant selection failed."); setBusy(false); return }
		router.push(next); router.refresh()
	}

	return <main className="mx-auto flex min-h-screen max-w-md items-center px-6"><form onSubmit={submit} className="w-full space-y-4 rounded-xl border bg-white p-8 shadow-sm"><div><div className="text-xs font-semibold tracking-widest text-blue-700">AXATY</div><h1 className="mt-2 text-2xl font-semibold">Command Center login</h1><p className="mt-1 text-sm text-slate-600">Sign in to your client tenant. Amazon live changes remain approval-gated.</p></div><label className="block text-sm font-medium">Email<input required name="email" type="email" autoComplete="email" className="mt-1 w-full rounded border px-3 py-2" /></label><label className="block text-sm font-medium">Password<input required name="password" type="password" autoComplete="current-password" className="mt-1 w-full rounded border px-3 py-2" /></label><label className="block text-sm font-medium">Tenant ID<input required name="tenantId" defaultValue={tenantId} className="mt-1 w-full rounded border px-3 py-2 font-mono text-xs" /></label>{error && <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}<button disabled={busy} className="w-full rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-50">{busy ? "Signing in…" : "Sign in"}</button><p className="text-xs text-slate-500">Accounts are created by the tenant owner or admin. Public sign-up is disabled.</p></form></main>
}
