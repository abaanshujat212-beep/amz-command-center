"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import type { ReactNode } from "react"
import { MobileBottomNav, MobileTopNav } from "./mobile-nav"

export function AppShell({ sidebar, status, children }: { sidebar: ReactNode; status: ReactNode; children: ReactNode }) {
	const pathname = usePathname()
	if (pathname === "/login") return children
	if (pathname.startsWith("/settings/")) {
		return <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-50 pb-20 md:pb-0"><header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur"><div className="mx-auto flex min-h-16 max-w-screen-2xl items-center justify-between gap-3 px-3 sm:px-4 md:px-8"><div className="flex min-w-0 items-center gap-3 md:gap-5"><Link href="/" aria-label="Close settings" className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-200 text-xl text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900">×</Link><div className="min-w-0"><span className="font-bold tracking-tight">AXA<span className="text-blue-600">TY</span></span><span className="ml-2 border-l pl-2 text-sm font-medium text-slate-500 md:ml-3 md:pl-3">Settings</span></div></div><div className="flex items-center gap-2"><MobileTopNav />{status}</div></div></header><main className="mx-auto max-w-screen-2xl px-3 py-4 sm:px-4 md:px-8 md:py-8">{children}</main><MobileBottomNav /></div>
	}

	return <div className="min-h-screen pb-20 md:pb-0 md:pl-64">{sidebar}<header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur"><div className="flex min-h-16 items-center justify-between gap-3 px-3 sm:px-4 md:justify-end md:px-8"><div className="flex items-center gap-3 md:hidden"><span className="font-semibold tracking-tight">AXATY</span><MobileTopNav /></div>{status}</div></header><main className="mx-auto max-w-7xl px-3 py-4 sm:px-4 md:px-8 md:py-8">{children}</main><MobileBottomNav /></div>
}
