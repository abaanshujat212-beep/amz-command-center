"use client"

import { useState, useTransition } from "react"
import { createApiKey } from "./actions"

export function CreateKeyForm() {
	const [token, setToken] = useState<string | null>(null)
	const [pending, startTransition] = useTransition()
	return <div className="rounded border bg-white p-4"><h2 className="font-medium">Create platform API key</h2><p className="mt-1 text-sm text-slate-600">Keys are shown once. Store them in your client secret manager; only a hash is saved.</p>{token && <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm"><div className="font-medium text-amber-900">Copy this key now</div><code className="mt-2 block break-all rounded bg-white p-2 text-xs">{token}</code></div>}<form className="mt-4 grid gap-3" action={(form) => startTransition(async () => setToken((await createApiKey(form)).token))}><input name="name" required minLength={2} maxLength={80} placeholder="Key name" className="rounded border px-3 py-2 text-sm"/><div className="flex flex-wrap gap-3 text-sm"><label className="flex items-center gap-2"><input type="checkbox" name="scope" value="read" defaultChecked/>Read</label><label className="flex items-center gap-2 text-slate-400"><input type="checkbox" disabled/>Write disabled</label></div><button disabled={pending} className="w-fit rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:bg-slate-300">{pending ? "Creating…" : "Create key"}</button></form></div>
}
