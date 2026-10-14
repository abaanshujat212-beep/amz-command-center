import Link from "next/link"

const links = [
	{ href: "/search-terms", label: "Ads search terms" },
	{ href: "/sqp", label: "Own-product intelligence" },
	{ href: "/search-trends", label: "Market trends" },
] as const

export function SearchIntelligenceNav({ active }: { active: string }) {
	return <nav aria-label="Search intelligence views" className="flex flex-wrap gap-2 border-b border-slate-200 pb-3">
		{links.map(link => <Link key={link.href} href={link.href} aria-current={active === link.href ? "page" : undefined} className={active === link.href ? "rounded bg-slate-900 px-3 py-1.5 text-sm text-white" : "rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"}>{link.label}</Link>)}
	</nav>
}
