"use client"

import { authClient } from "@/lib/auth-client"

export function AccountMenu() {
	return <button className="text-xs text-slate-500 hover:underline" onClick={async () => { await authClient.signOut(); window.location.href = "/login" }}>Sign out</button>
}
