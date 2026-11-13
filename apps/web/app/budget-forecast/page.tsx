import Link from "next/link"
import { SettingsHeading } from "@/components/settings-ui"
import { withTenant } from "@/lib/db"
import { money, percent, reportDate, stamp } from "@/lib/format"
import { monthlyBudgetForecast, recentDryRunSummaries } from "@/lib/queries-budget-forecast"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
	return <div className="rounded-lg border bg-white p-4"><div className="text-xs uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>{note && <p className="mt-1 text-xs text-slate-500">{note}</p>}</div>
}

function range(low: number | null, base: number | null, high: number | null, currency: string) {
	if (low === null || base === null || high === null) return "—"
	return `${money(low)} – ${money(high)} ${currency}`
}

export default async function BudgetForecastPage() {
	const tenantId = await currentTenantId()
	const { forecast, simulations } = await withTenant(tenantId, async client => ({
		forecast: await monthlyBudgetForecast(client),
		simulations: await recentDryRunSummaries(client),
	}))
	return <div className="space-y-6">
		<SettingsHeading title="Budget forecast & simulator" description="Conservative month-end spend and ad-attributed sales scenarios from successfully ingested, settled campaign days. Forecasts describe scenarios, not guarantees." />
		{!forecast || forecast.confidence === "INSUFFICIENT_DATA" ? <section className="rounded-lg border border-dashed bg-white p-8 text-sm text-slate-600"><h2 className="font-medium text-slate-900">Not enough settled campaign data to forecast yet</h2><p className="mt-2">A forecast needs at least one successful campaign-report day in this month. Missing ingestion days are reported as gaps; they are not treated as zero-spend days.</p></section> : <>
			<section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
				<Kpi label="Month-end spend scenario" value={range(forecast.spend_forecast_low, forecast.spend_forecast_base, forecast.spend_forecast_high, forecast.tenant_currency)} note={`Base ${money(forecast.spend_forecast_base)} ${forecast.tenant_currency}`} />
				<Kpi label="Month-end attributed sales" value={range(forecast.sales_forecast_low, forecast.sales_forecast_base, forecast.sales_forecast_high, forecast.tenant_currency)} note="Advertising-attributed sales, not total store sales" />
				<Kpi label="Forecast confidence" value={`${forecast.confidence} · ${percent(forecast.confidence_score)}`} note={`${forecast.covered_days}/${forecast.elapsed_days} elapsed settled dates covered`} />
				<Kpi label="Monthly budget governance" value={forecast.monthly_limit === null ? "Not configured" : `${money(forecast.monthly_limit)} ${forecast.limit_currency}`} note={forecast.limit_status.replaceAll("_", " ").toLowerCase()} />
			</section>
			<section className="rounded-lg border bg-white p-4">
				<h2 className="font-semibold">Horizon and evidence</h2>
				<dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
					<div><dt className="text-xs text-slate-500">Forecast month</dt><dd>{reportDate(forecast.month_start)} – {reportDate(forecast.month_end)}</dd></div>
					<div><dt className="text-xs text-slate-500">Settled through</dt><dd>{reportDate(forecast.settled_through)} · {forecast.reporting_timezone}</dd></div>
					<div><dt className="text-xs text-slate-500">Observed spend</dt><dd>{money(forecast.observed_spend)} across {forecast.covered_days} covered days</dd></div>
					<div><dt className="text-xs text-slate-500">Estimated spend to date</dt><dd>{forecast.estimated_spend_to_date === null ? "—" : money(forecast.estimated_spend_to_date)} <span className="text-xs text-slate-500">({forecast.missing_days} missing days estimated)</span></dd></div>
				</dl>
				<div className="mt-4 rounded bg-slate-50 p-3 text-xs text-slate-600">{forecast.assumptions} Scenarios use mean daily results ± one population standard deviation; this range is not a statistical guarantee. More missing days and volatility reduce confidence. No spend or sales values are written back to Amazon.</div>
				<div className="mt-3 flex flex-wrap gap-4 text-sm"><Link href="/budget-health" className="text-blue-700 hover:underline">Daily budget health →</Link><Link href="/settings/portfolio-budgets" className="text-blue-700 hover:underline">Configure portfolio limits →</Link></div>
			</section>
		</>}
		<section>
			<div className="mb-3 flex flex-wrap items-baseline justify-between gap-3"><div><h2 className="font-semibold">Recent dry-run summaries</h2><p className="text-sm text-slate-600">Historical configuration previews reuse the existing no-write simulator and show affected entities and exposure.</p></div><Link href="/settings/config-rollouts" className="text-sm text-blue-700 hover:underline">Open simulator →</Link></div>
			{simulations.length === 0 ? <div className="rounded-lg border border-dashed bg-white p-5 text-sm text-slate-500">No dry-run simulations recorded.</div> : <div className="space-y-2">{simulations.map(sim => <article key={sim.id} className="rounded-lg border bg-white p-4"><div className="flex flex-wrap justify-between gap-2"><div><span className="font-medium">{sim.state ?? "Preview"}</span><span className="ml-2 text-xs text-slate-500">{stamp(sim.created_at)}</span></div><div className="text-sm">{sim.affected_count}/{sim.entity_count} affected · {sim.protected_excluded} protected · {percent(sim.risk_score)} risk</div></div><pre className="mt-2 overflow-x-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(sim.proposed_values, null, 2)}</pre></article>)}</div>}
		</section>
	</div>
}
