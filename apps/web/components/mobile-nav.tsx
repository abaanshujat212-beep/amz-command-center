"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

const tabs = [["/", "Home"], ["/copilot", "Copilot"], ["/approvals", "Approve"], ["/history", "History"], ["/settings/profile", "Settings"]] as const
const more = [["/search-terms", "Search terms"], ["/placements", "Placements"], ["/opportunities", "Products"], ["/sqp", "SQP"], ["/economics", "Economics"], ["/verification", "Verification"]] as const

function active(pathname: string, href: string): boolean { return href === "/" ? pathname === href : pathname.startsWith(href) }

export function MobileTopNav() {
	const pathname = usePathname()
	if (pathname === "/login") return null
	return <details className="md:hidden"><summary className="list-none rounded border border-slate-200 px-3 py-2 text-sm text-slate-700">Menu</summary><div className="absolute left-4 right-4 top-14 z-50 grid gap-1 rounded-xl border bg-white p-2 shadow-lg">{more.map(([href,label]) => <Link key={href} href={href} className={active(pathname, href) ? "rounded bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700" : "rounded px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"}>{label}</Link>)}</div></details>
}

export function MobileBottomNav() {
	const pathname = usePathname()
	if (pathname === "/login") return null
	return <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-slate-200 bg-white/95 px-1 py-1 text-center text-[11px] backdrop-blur md:hidden">{tabs.map(([href,label]) => <Link key={href} href={href} className={active(pathname, href) ? "rounded-lg bg-blue-50 px-1 py-2 font-medium text-blue-700" : "rounded-lg px-1 py-2 text-slate-600 hover:bg-slate-50"}>{label}</Link>)}</nav>
}
