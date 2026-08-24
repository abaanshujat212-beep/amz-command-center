import Link from "next/link"
import { withTenant } from "@/lib/db"
import { acosTone, count, money, percent, reportDate } from "@/lib/format"
import {
	accountTotals,
	campaignPerformance,
	openFindings,
	type CampaignRow,
} from "@/lib/queries"
import { ALLOWED_WINDOWS, parseDays, windowHref, type Window } from "@/lib/range"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

function Kpi({
	label,
	value,
	note,
}: {
	label: string
	value: string
	note?: string
}) {
	return (
		<div className="rounded-lg border border-slate-200 bg-white p-4">
			<div className="text-xs uppercase tracking-wide text-slate-500">
				{label}
			</div>
			<div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
			{note && <div className="mt-1 text-xs text-slate-500">{note}</div>}
		</div>
	)
}

function WindowPicker({ days }: { days: Window }) {
	return (
		<div className="flex gap-1 text-xs">
			{ALLOWED_WINDOWS.map((d) => (
				<Link
					key={d}
					href={windowHref("/", d)}
					className={
						d === days
							? "rounded bg-slate-900 px-2 py-1 text-white"
							: "rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-100"
					}
				>
					{d}d
				</Link>
			))}
		</div>
	)
}

function AcosCell({ row }: { row: CampaignRow }) {
	const tone = acosTone(row.acos, row.break_even_acos)
	return (
		<td className={`num px-3 py-2 tone-${tone}`}>
			{percent(row.acos)}
			{row.economics_incomplete && (
				<span
					className="ml-1 text-slate-400"
					title="No cost data for at least one advertised ASIN, so break-even is unknown"
				>
					?
				</span>
			)}
		</td>
	)
}

export default async function CommandCenter({
	searchParams,
}: {
	searchParams: Promise<{ days?: string }>
}) {
	const sp = await searchParams
	const days = parseDays(sp.days)
	const tenantId = currentTenantId()

	const { totals, campaigns, findings } = await withTenant(
		tenantId,
		async (c) => ({
			totals: await accountTotals(c, days),
			campaigns: await campaignPerformance(c, days),
			findings: await openFindings(c, 20),
		}),
	)

	if (campaigns.length === 0) {
		return (
			<div className="rounded-lg border border-slate-200 bg-white p-8">
				<h1 className="text-lg font-semibold">No settled campaign data yet</h1>
				<p className="mt-2 max-w-2xl text-sm text-slate-600">
					This is the expected state until the Ads ingest has run and dbt has
					built the marts. It is not an error, and it is deliberately not a
					screen full of zeroes &mdash; zero spend and no data look identical on
					a dashboard and mean opposite things.
				</p>
				<p className="mt-2 max-w-2xl text-sm text-slate-600">
					Note that only settled days appear here. Amazon keeps attributing
					conversions for several days after a click, so the newest days are
					held back until they stop moving.
				</p>
			</div>
		)
	}

	return (
		<div className="space-y-8">
			<section>
				<div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
					<h1 className="text-lg font-semibold">PPC Command Center</h1>
					<div className="flex items-center gap-3">
						<span className="text-xs text-slate-500">
							last {days} settled days
							{totals?.data_through &&
								` \u00b7 through ${reportDate(totals.data_through)}`}
						</span>
						<WindowPicker days={days} />
					</div>
				</div>
				<div className="grid grid-cols-2 gap-3 md:grid-cols-4">
					<Kpi label="Ad spend" value={money(totals?.cost ?? 0)} />
					<Kpi label="Ad sales" value={money(totals?.sales ?? 0)} />
					<Kpi
						label="ACOS"
						value={percent(totals?.acos ?? null)}
						note="spend \u00f7 ad sales, recomputed from totals"
					/>
					<Kpi
						label="Campaigns"
						value={String(totals?.campaigns ?? 0)}
						note={`${count(totals?.orders ?? 0)} orders`}
					/>
				</div>
			</section>

			<section>
				<table className="w-full border-collapse bg-white text-sm">
					<thead>
						<tr className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500">
							<th className="px-3 py-2">Campaign</th>
							<th className="px-3 py-2 text-right">Spend</th>
							<th className="px-3 py-2 text-right">Sales</th>
							<th className="px-3 py-2 text-right">ACOS</th>
							<th className="px-3 py-2 text-right">Break-even</th>
							<th className="px-3 py-2 text-right">CTR</th>
							<th className="px-3 py-2 text-right">CVR</th>
							<th className="px-3 py-2 text-right">CPC</th>
							<th className="px-3 py-2 text-right">Budget used</th>
						</tr>
					</thead>
					<tbody>
						{campaigns.map((row) => (
							<tr
								key={row.campaign_id}
								className="border-b border-slate-100 hover:bg-slate-50"
							>
								<td className="px-3 py-2">
									<Link
										href={`/campaigns/${encodeURIComponent(row.campaign_id)}?days=${days}`}
										className="font-medium text-blue-700 hover:underline"
									>
										{row.campaign_name}
									</Link>
									<div className="text-xs text-slate-500">
										{row.campaign_status ?? "unknown"}
										{row.targeting_type ? ` \u00b7 ${row.targeting_type}` : ""}
									</div>
								</td>
								<td className="num px-3 py-2">{money(row.cost)}</td>
								<td className="num px-3 py-2">{money(row.sales)}</td>
								<AcosCell row={row} />
								<td className="num px-3 py-2 text-slate-500">
									{row.break_even_acos === null ? (
										<span title="Fill sku_cost_ledger to enable profit rules">
											no cost data
										</span>
									) : (
										percent(row.break_even_acos)
									)}
								</td>
								<td className="num px-3 py-2">{percent(row.ctr, 2)}</td>
								<td className="num px-3 py-2">{percent(row.cvr)}</td>
								<td className="num px-3 py-2">{money(row.cpc)}</td>
								<td className="num px-3 py-2">
									{percent(row.budget_utilisation, 0)}
								</td>
							</tr>
						))}
					</tbody>
				</table>
				<p className="mt-2 text-xs text-slate-500">
					ACOS is coloured against each campaign&rsquo;s own break-even, not a
					fixed target. A dash means the metric cannot be computed &mdash; never
					zero. Click a campaign for its keywords.
				</p>
			</section>

			<section>
				<h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
					Findings ({findings.length})
				</h2>
				{findings.length === 0 ? (
					<p className="text-sm text-slate-500">
						Nothing flagged. Diagnostics never change anything on Amazon; they
						only point at something worth a human look.
					</p>
				) : (
					<ul className="space-y-2">
						{findings.map((f) => (
							<li
								key={f.id}
								className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm"
							>
								<span className="font-medium">{f.rule_name ?? f.rule_code}</span>
								<span className="text-slate-500">
									{" "}
									&middot; {f.entity_type} {f.entity_id}
								</span>
								<div className="text-slate-700">{f.reason_text}</div>
							</li>
						))}
					</ul>
				)}
				<div className="mt-4 flex gap-4 text-sm">
					<Link href="/approvals" className="text-blue-700 hover:underline">
						Approval queue &rarr;
					</Link>
					<Link
						href={`/search-terms?days=${days}`}
						className="text-blue-700 hover:underline"
					>
						Search terms &rarr;
					</Link>
					<Link
						href={`/history?days=${days}`}
						className="text-blue-700 hover:underline"
					>
						Decision history &rarr;
					</Link>
				</div>
			</section>
		</div>
	)
}
