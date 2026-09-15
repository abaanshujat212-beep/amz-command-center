"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { DOMAIN_GROUPS, navigationState, type ModuleNavigationState } from "@/lib/domain-navigation"

function NavLink({ href, label }: { href: string; label: string }) {
	const pathname = usePathname()
	const active = href === "/" ? pathname === href : pathname.startsWith(href)
	return <Link href={href} aria-current={active ? "page" : undefined} className={`block rounded-lg px-3 py-2 text-sm ${active ? "bg-blue-50 font-medium text-blue-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"}`}>{label}</Link>
}

export function SidebarNav({ moduleStates = [] }: { moduleStates?: readonly ModuleNavigationState[] }) {
	return <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-slate-200 bg-white md:flex"><div className="flex h-16 items-center border-b border-slate-100 px-6"><span className="text-xl font-bold tracking-tight">AXA<span className="text-blue-600">TY</span></span></div><nav aria-label="Domain navigation" className="flex flex-1 flex-col overflow-y-auto p-3">{DOMAIN_GROUPS.map(group => <section key={group.label} className="mb-3"><p className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{group.label}</p>{group.links.map(link => { const state = navigationState(link, moduleStates); if (!state.visible) return null; return state.enabled ? <NavLink key={link.href} href={link.href} label={link.label}/> : <div key={link.href} title={state.reason ?? "Module unavailable"} className="rounded-lg px-3 py-2 text-sm text-slate-400" aria-disabled="true">{link.label}<span className="ml-2 text-[10px]">{state.reason}</span></div> })}</section>)}<div className="mt-auto border-t pt-3"><NavLink href="/settings/profile" label="Settings"/></div></nav></aside>
}
