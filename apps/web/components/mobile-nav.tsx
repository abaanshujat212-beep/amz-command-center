"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { DOMAIN_GROUPS } from "@/lib/domain-navigation"

const tabs = [["/", "Home"], ["/opportunities", "Products"], ["/approvals", "Decisions"], ["/campaigns", "Ads"], ["/settings/profile", "More"]] as const
const more = DOMAIN_GROUPS.flatMap(group => group.links).filter(link => !tabs.some(([href]) => href === link.href))
function active(pathname: string, href: string) { return href === "/" ? pathname === href : pathname.startsWith(href) }
export function MobileTopNav() { const pathname = usePathname(); if (pathname === "/login") return null; return <details className="md:hidden"><summary className="list-none rounded border px-3 py-2 text-sm">Menu</summary><div className="absolute left-4 right-4 top-14 z-50 grid gap-1 rounded-xl border bg-white p-2 shadow-lg">{more.map(link => <Link key={link.href} href={link.href} className={active(pathname, link.href) ? "rounded bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700" : "rounded px-3 py-2 text-sm text-slate-700"}>{link.label}</Link>)}</div></details> }
export function MobileBottomNav() { const pathname = usePathname(); if (pathname === "/login") return null; return <nav aria-label="Mobile domain navigation" className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t bg-white/95 px-1 py-1 text-center text-[11px] md:hidden">{tabs.map(([href,label]) => <Link key={href} href={href} className={active(pathname, href) ? "rounded-lg bg-blue-50 px-1 py-2 font-medium text-blue-700" : "rounded-lg px-1 py-2 text-slate-600"}>{label}</Link>)}</nav> }
