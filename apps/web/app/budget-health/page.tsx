import Link from "next/link"
import { budgetHealth } from "@/lib/queries-budget-health"
import { currentTenantId } from "@/lib/session"
import { withTenant } from "@/lib/db"
import { money, percent, reportDate } from "@/lib/format"
import { ALLOWED_WINDOWS, parseDays, windowHref, type Window } from "@/lib/range"

export const dynamic = "force-dynamic"

function WindowPicker({ days }: { days: Window }) {
	return <div className="flex gap-1 text-xs">{ALLOWED_WINDOWS.map(value => <Link key={value} href={windowHref("/budget-health", value)} className={value === days ? "rounded bg-slate-900 px-2 py-1 text-white" : "rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-100"}>{value}d</Link>)}</div>
}

function badge(value: string) {
	const tone = value === "capped" || value === "over_budget_delivery" || value === "high" || value === "inefficient_consumer"
		? "bg-amber-50 text-amber-800"
		: value === "profitable_dark" || value === "profitable" || value === "low" || value === "on_track"
			? "bg-emerald-50 text-emerald-800"
			: value === "unknown" || value === "unknown_economics" || value === "insufficient_data" || value === "no_attributed_sales"
				? "bg-slate-100 text-slate-600"
				: "bg-blue-50 text-blue-800"
	return <span className={`inline-flex rounded px-2 py-1 text-xs font-medium ${tone}`}>{value.replaceAll("_", " ")}</span>
}

export default async function BudgetHealthPage({ searchParams }: { searchParams: Promise<{ days?: string }> }) {
	const days = parseDays((await searchParams).days)
	const rows = await withTenant(await currentTenantId(), client => budgetHealth(client, days))
	return <div className="space-y-5">
		<header className="flex flex-wrap items-end justify-between gap-3">
			<div><h1 className="text-lg font-semibold">Daily budget health</h1><p className="mt-1 text-sm text-slate-600">Settled campaign delivery and seven-day efficiency signals. These indicators are read-only and never change budgets.</p></div>
			<WindowPicker days={days}/>
		</header>
		<section className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700">
			<h2 className="font-semibold">How statuses are calculated</h2>
			<ul className="mt-2 grid gap-1 text-xs text-slate-600 md:grid-cols-2">
				<li><b>Capped:</b> daily spend is at least 98% of the recorded budget.</li>
				<li><b>Over-budget delivery:</b> spend exceeds the nominal daily budget; this alone is not a policy violation.</li>
				<li><b>Underspend:</b> daily utilization is below 50%.</li>
				<li><b>Exhaustion risk:</b> high at 3+ capped days in the last 7 calendar days; watch at 1–2; low only with at least 5 settled days and no capped day.</li>
				<li><b>Profitable dark:</b> no impressions/spend on the latest settled day, while complete seven-day economics are below break-even ACOS.</li>
				<li><b>Inefficient consumer:</b> seven-day utilization is at least 90% and ACOS is above complete break-even economics.</li>
			</ul>
			<p className="mt-2 text-xs text-slate-500">Missing budget, economics, or settled coverage stays unknown. The nominal daily budget can be exceeded under Amazon delivery rules; investigate before drawing conclusions.</p>
		</section>
		{rows.length === 0 ? <div className="rounded-lg border border-dashed bg-white p-8 text-sm text-slate-600">No settled campaign budget rows in this window. Ingest campaign reports and build dbt marts first; missing rows are not treated as zero utilization.</div> : <div className="overflow-x-auto rounded-lg border bg-white">
			<table className="w-full text-sm"><thead><tr className="border-b text-left text-xs uppercase text-slate-500"><th className="p-3">Campaign</th><th className="p-3">Budget status</th><th className="p-3 num">Latest day</th><th className="p-3 num">Spend / budget</th><th className="p-3">Exhaustion</th><th className="p-3">Efficiency signal</th><th className="p-3 num">7d capped days</th><th className="p-3 num">7d ACOS / break-even</th></tr></thead><tbody>
				{rows.map(row => <tr key={row.campaign_id} className="border-b align-top"><td className="p-3"><Link href={`/campaigns/${encodeURIComponent(row.campaign_id)}`} className="font-medium text-blue-700 hover:underline">{row.campaign_name}</Link><div className="text-xs text-slate-500">{row.campaign_status ?? "status unknown"} · {reportDate(row.report_date)}</div></td><td className="p-3">{badge(row.budget_status)}</td><td className="p-3 num">{money(row.spend)}</td><td className="p-3 num">{row.budget_amount === null ? "—" : money(row.budget_amount)}<div className="text-xs text-slate-500">{percent(row.budget_utilisation)}</div></td><td className="p-3">{badge(row.exhaustion_risk)}</td><td className="p-3">{badge(row.efficiency_signal)}</td><td className="p-3 num">{row.capped_days_7d} / 7<div className="text-xs text-slate-500">{row.settled_days_7d} settled days</div></td><td className="p-3 num">{percent(row.acos_7d)}<div className="text-xs text-slate-500">break-even {percent(row.break_even_acos_7d)}</div></td></tr>)}
			</tbody></table>
		</div>}
	</div>
}
