"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

const sections = [
	["/settings/profile", "My profile"], ["/settings/client", "Company profile"],
	["/settings/members", "Team & roles"], ["/settings/ai", "AI models"],
	["/settings/amazon", "Amazon integrations"], ["/settings/email", "Email services"],
	["/settings/email-templates", "Email templates"], ["/settings/billing", "Billing"],
	["/settings/api-keys", "API keys"], ["/settings/audit", "Audit logs"],
] as const

export function SettingsNav() {
	const pathname = usePathname()
	return <nav aria-label="Settings navigation" className="space-y-1">{sections.map(([href,label]) => <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined} className={`block rounded-lg px-3 py-2 text-sm transition-colors ${pathname === href ? "bg-blue-50 font-medium text-blue-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"}`}>{label}</Link>)}</nav>
}
