"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import type { ReactNode } from "react"

export function AppShell({ sidebar, status, children }: { sidebar: ReactNode; status: ReactNode; children: ReactNode }) {
	const pathname = usePathname()
	if (pathname === "/login") return children
	if (pathname.startsWith("/settings/")) {
		return <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-50"><header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur"><div className="mx-auto flex min-h-16 max-w-screen-2xl items-center justify-between gap-4 px-4 md:px-8"><div className="flex items-center gap-5"><Link href="/" aria-label="Close settings" className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 text-xl text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900">×</Link><div><span className="font-bold tracking-tight">AXA<span className="text-blue-600">TY</span></span><span className="ml-3 border-l pl-3 text-sm font-medium text-slate-500">Settings</span></div></div>{status}</div></header><main className="mx-auto max-w-screen-2xl px-4 py-6 md:px-8 md:py-8">{children}</main></div>
	}

	return <div className="min-h-screen md:pl-64">{sidebar}<header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur"><div className="flex min-h-16 items-center justify-between gap-4 px-4 md:justify-end md:px-8"><span className="font-semibold tracking-tight md:hidden">AXATY</span>{status}</div></header><main className="mx-auto max-w-7xl px-4 py-6 md:px-8 md:py-8">{children}</main></div>
}
