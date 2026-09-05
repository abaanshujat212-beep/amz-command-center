"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import type { ReactNode } from "react"

const primary = [
	["/", "Command Center", "grid"],
	["/search-terms", "Search terms", "search"],
	["/opportunities", "Products", "box"],
	["/sqp", "SQP opportunities", "spark"],
	["/economics", "Economics", "chart"],
] as const

const operations = [
	["/approvals", "Approvals", "check"],
	["/history", "History", "clock"],
] as const

function Icon({ name }: { name: string }) {
	const paths: Record<string, ReactNode> = {
		grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
		search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
		box: <><path d="m4 7 8-4 8 4-8 4-8-4Z"/><path d="m4 7 8 4 8-4v10l-8 4-8-4V7Z"/></>,
		spark: <><path d="m12 3 1.4 4.1L17 9l-3.6 1.9L12 15l-1.4-4.1L7 9l3.6-1.9L12 3Z"/><path d="m5 14 .8 2.2L8 17l-2.2.8L5 20l-.8-2.2L2 17l2.2-.8L5 14Z"/></>,
		chart: <><path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M22 20H2"/></>,
		check: <><rect x="3" y="3" width="18" height="18" rx="3"/><path d="m8 12 3 3 6-7"/></>,
		clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
		users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/></>,
		settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/></>,
	}
	return <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}

function NavLink({ href, label, icon }: { href: string; label: string; icon: string }) {
	const pathname = usePathname()
	const active = label === "Settings" ? pathname.startsWith("/settings/") && pathname !== "/settings/members" : href === "/" ? pathname === href : pathname.startsWith(href)
	return <Link href={href} aria-current={active ? "page" : undefined} className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${active ? "bg-blue-50 font-medium text-blue-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"}`}><Icon name={icon}/><span>{label}</span></Link>
}

export function SidebarNav() {
	return <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-slate-200 bg-white md:flex"><div className="flex h-16 items-center border-b border-slate-100 px-6"><span className="text-xl font-bold tracking-tight text-slate-950">AXA<span className="text-blue-600">TY</span></span></div><nav aria-label="Main navigation" className="flex flex-1 flex-col overflow-y-auto p-3"><div className="space-y-1">{primary.map(([href, label, icon]) => <NavLink key={href} href={href} label={label} icon={icon}/>)}</div><div className="my-4 border-t border-slate-100"/><p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">Operations</p><div className="space-y-1">{operations.map(([href, label, icon]) => <NavLink key={href} href={href} label={label} icon={icon}/>)}</div><div className="mt-auto space-y-1 border-t border-slate-100 pt-3"><NavLink href="/settings/members" label="Team" icon="users"/><NavLink href="/settings/profile" label="Settings" icon="settings"/></div></nav></aside>
}
