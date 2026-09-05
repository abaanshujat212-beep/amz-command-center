"use client"

import { usePathname } from "next/navigation"
import type { ReactNode } from "react"

export function AppShell({ sidebar, status, children }: { sidebar: ReactNode; status: ReactNode; children: ReactNode }) {
	const pathname = usePathname()
	if (pathname === "/login") return children

	return <div className="min-h-screen md:pl-64">{sidebar}<header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur"><div className="flex min-h-16 items-center justify-between gap-4 px-4 md:justify-end md:px-8"><span className="font-semibold tracking-tight md:hidden">AXATY</span>{status}</div></header><main className="mx-auto max-w-7xl px-4 py-6 md:px-8 md:py-8">{children}</main></div>
}
