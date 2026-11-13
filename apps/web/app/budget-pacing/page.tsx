import Link from "next/link"
import { currentTenantId } from "@/lib/session"
import { withTenant } from "@/lib/db"
import { money, percent, reportDate } from "@/lib/format"
import { budgetPacing } from "@/lib/queries-budget-pacing"
import { ALLOWED_WINDOWS, parseDays, windowHref, type Window } from "@/lib/range"

export const dynamic = "force-dynamic"

function WindowPicker({ days }: { days: Window }) {
	return <div className="flex gap-1 text-xs">{ALLOWED_WINDOWS.map(value => <Link key={value} href={windowHref("/budget-pacing", value)} className={value === days ? "rounded bg-slate-900 px-2 py-1 text-white" : "rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-100"}>{value}d</Link>)}</div>
}

function badge(value: string) {
	const style = value === "under_paced" ? "bg-blue-50 text-blue-800" : value === "over_paced" ? "bg-amber-50 text-amber-800" : value === "on_pace" ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-600"
	return <span className={`inline-flex rounded px-2 py-1 text-xs font-medium ${style}`}>{value.replaceAll("_", " ")}</span>
}

export default async function BudgetPacingPage({ searchParams }: { searchParams: Promise<{ days?: string }> }) {
	const days = parseDays((await searchParams).days)
	const rows = await withTenant(await currentTenantId(), client => budgetPacing(client, days))
	return <div className="space-y-5">
		<header className="flex flex-wrap items-end justify-between gap-3">
			<div><h1 className="text-lg font-semibold">Daily budget pacing</h1><p className="mt-1 text-sm text-slate-600">Latest settled campaign delivery compared with its nominal daily budget. Read-only diagnostic; no budget changes are made.</p></div>
			<WindowPicker days={days}/>
		</header>
		<section className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700">
			<h2 className="font-semibold">How to read pacing</h2>
			<p className="mt-2 text-xs text-slate-600">The pace ratio is latest settled daily spend ÷ recorded daily budget. Under 80% is under-paced, 80–120% is on-pace, and over 120% is over-paced. Amazon may deliver above the nominal daily budget under its delivery rules. This is daily evidence, not an hourly curve; hourly pacing remains unavailable until Marketing Stream data is connected.</p>
		</section>
		{rows.length === 0 ? <div className="rounded-lg border border-dashed bg-white p-8 text-sm text-slate-600">No settled campaign budget rows in this window. Ingest campaign reports and build dbt marts first.</div> : <div className="overflow-x-auto rounded-lg border bg-white">
			<table className="w-full text-sm"><thead><tr className="border-b text-left text-xs uppercase text-slate-500"><th className="p-3">Campaign</th><th className="p-3">Pacing</th><th className="p-3 num">Latest settled day</th><th className="p-3 num">Spend / daily budget</th><th className="p-3 num">Pace ratio</th><th className="p-3 num">7d capped days</th></tr></thead><tbody>
				{rows.map(row => <tr key={row.campaign_id} className="border-b align-top"><td className="p-3"><Link href={`/campaigns/${encodeURIComponent(row.campaign_id)}`} className="font-medium text-blue-700 hover:underline">{row.campaign_name}</Link><div className="text-xs text-slate-500">{row.campaign_status ?? "status unknown"}</div></td><td className="p-3">{badge(row.pacing_status)}</td><td className="p-3 num">{money(row.spend)}<div className="text-xs text-slate-500">{reportDate(row.report_date)}</div></td><td className="p-3 num">{row.budget_amount === null ? "—" : money(row.budget_amount)}</td><td className="p-3 num">{percent(row.pace_ratio)}</td><td className="p-3 num">{row.capped_days_7d} / 7<div className="text-xs text-slate-500">{row.settled_days_7d} settled days</div></td></tr>)}
			</tbody></table>
		</div>}
		<p className="text-xs text-slate-500">See <Link className="text-blue-700 hover:underline" href="/budget-health">daily budget health</Link> for exhaustion and efficiency signals.</p>
	</div>
}
