import Link from "next/link"
import { notFound } from "next/navigation"
import { withTenant } from "@/lib/db"
import {
	acosTone,
	benchmarkTone,
	count,
	money,
	percent,
	reportDate,
} from "@/lib/format"
import {
	campaignHeader,
	keywordPerformance,
	type KeywordRow,
} from "@/lib/queries-drilldown"
import { ALLOWED_WINDOWS, parseDays, windowHref, type Window } from "@/lib/range"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

const VERDICT_TONE: Record<string, string> = {
	strong: "tone-good",
	profitable: "tone-good",
	marginal: "tone-warn",
	losing: "tone-bad",
	no_sales: "tone-bad",
	no_data: "tone-unknown",
	unknown: "tone-unknown",
}

function WindowPicker({
	days,
	campaignId,
}: {
	days: Window
	campaignId: string
}) {
	return (
		<div className="flex gap-1 text-xs">
			{ALLOWED_WINDOWS.map((d) => (
				<Link
					key={d}
					href={windowHref(`/campaigns/${encodeURIComponent(campaignId)}`, d)}
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

function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
	return (
		<div className="rounded-lg border border-slate-200 bg-white p-3">
			<div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
			<div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
			{note && <div className="mt-1 text-xs text-slate-500">{note}</div>}
		</div>
	)
}

function KeywordRowView({ k }: { k: KeywordRow }) {
	return (
		<tr className="border-b border-slate-100 hover:bg-slate-50">
			<td className="px-3 py-2">
				<div className="font-medium">{k.keyword_text}</div>
				<div className="text-xs text-slate-500">
					{k.match_type ?? "unknown match"}
					{k.keyword_status ? ` \u00b7 ${k.keyword_status}` : ""}
				</div>
			</td>
			<td className="num px-3 py-2">{money(k.bid)}</td>
			<td className="num px-3 py-2">{count(k.impressions)}</td>
			<td className="num px-3 py-2">{count(k.clicks)}</td>
			<td className="num px-3 py-2">{money(k.cost)}</td>
			<td className="num px-3 py-2">{money(k.sales)}</td>
			<td className={`num px-3 py-2 ${"tone-" + acosTone(k.acos, k.break_even_acos)}`}>
				{percent(k.acos)}
			</td>
			<td
				className={`num px-3 py-2 tone-${benchmarkTone(k.ctr, k.account_ctr)}`}
				title={`account CTR ${percent(k.account_ctr, 2)}`}
			>
				{percent(k.ctr, 2)}
			</td>
			<td
				className={`num px-3 py-2 tone-${benchmarkTone(k.cvr, k.account_cvr)}`}
				title={`account CVR ${percent(k.account_cvr)}`}
			>
				{percent(k.cvr)}
			</td>
			<td className="num px-3 py-2">{money(k.cpc)}</td>
			<td className={`px-3 py-2 text-xs ${VERDICT_TONE[k.verdict] ?? "tone-unknown"}`}>
				{k.verdict.replace("_", " ")}
			</td>
		</tr>
	)
}

export default async function CampaignDetail({
	params,
	searchParams,
}: {
	params: Promise<{ campaignId: string }>
	searchParams: Promise<{ days?: string }>
}) {
	const { campaignId } = await params
	const sp = await searchParams
	const days = parseDays(sp.days)
	const tenantId = await currentTenantId()

	const { header, keywords } = await withTenant(tenantId, async (c) => ({
		header: await campaignHeader(c, campaignId, days),
		keywords: await keywordPerformance(c, campaignId, days, 200),
	}))

	// No settled rows for this id in this window. With RLS in force, another
	// tenant's campaign and a campaign that never existed are indistinguishable
	// here, and both answers are the same: not yours.
	if (header === null) notFound()

	return (
		<div className="space-y-6">
			<div>
				<Link href="/" className="text-xs text-blue-700 hover:underline">
					&larr; Command Center
				</Link>
				<div className="mt-1 flex flex-wrap items-baseline justify-between gap-3">
					<h1 className="text-lg font-semibold">{header.campaign_name}</h1>
					<WindowPicker days={days} campaignId={campaignId} />
				</div>
				<div className="text-xs text-slate-500">
					{header.campaign_status ?? "unknown"}
					{header.targeting_type ? ` \u00b7 ${header.targeting_type}` : ""}
					{" \u00b7 "}
					{header.days} settled days
					{header.data_through && ` \u00b7 through ${reportDate(header.data_through)}`}
				</div>
			</div>

			<div className="grid grid-cols-2 gap-3 md:grid-cols-5">
				<Kpi label="Spend" value={money(header.cost)} />
				<Kpi label="Sales" value={money(header.sales)} />
				<Kpi
					label="ACOS"
					value={percent(header.acos)}
					note={
						header.break_even_acos === null
							? "break-even unknown"
							: `break-even ${percent(header.break_even_acos)}`
					}
				/>
				<Kpi label="CPC" value={money(header.cpc)} note={`${count(header.clicks)} clicks`} />
				<Kpi
					label="Daily budget"
					value={money(header.budget_amount)}
					note="most recent settled day"
				/>
			</div>

			{header.economics_incomplete && (
				<div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">
					At least one advertised ASIN has no cost data, so break-even is a
					worst-case figure or missing entirely. Profit rules stay quiet in that
					state rather than guessing &mdash; fill <code>sku_cost_ledger</code>{" "}
					(#14).
				</div>
			)}

			<section>
				<div className="mb-2 flex items-baseline justify-between">
					<h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
						Keywords ({keywords.length})
					</h2>
					<Link
						href={`/search-terms?days=${days}&campaign=${encodeURIComponent(campaignId)}`}
						className="text-xs text-blue-700 hover:underline"
					>
						Search terms for this campaign &rarr;
					</Link>
				</div>

				{keywords.length === 0 ? (
					<p className="text-sm text-slate-500">
						No settled keyword rows in this window. Auto-targeted campaigns have
						no keywords by design; their spend appears against targets instead.
					</p>
				) : (
					<table className="w-full border-collapse bg-white text-sm">
						<thead>
							<tr className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500">
								<th className="px-3 py-2">Keyword</th>
								<th className="px-3 py-2 text-right">Bid</th>
								<th className="px-3 py-2 text-right">Impr.</th>
								<th className="px-3 py-2 text-right">Clicks</th>
								<th className="px-3 py-2 text-right">Spend</th>
								<th className="px-3 py-2 text-right">Sales</th>
								<th className="px-3 py-2 text-right">ACOS</th>
								<th className="px-3 py-2 text-right">CTR</th>
								<th className="px-3 py-2 text-right">CVR</th>
								<th className="px-3 py-2 text-right">CPC</th>
								<th className="px-3 py-2">Verdict</th>
							</tr>
						</thead>
						<tbody>
							{keywords.map((k) => (
								<KeywordRowView key={k.keyword_id} k={k} />
							))}
						</tbody>
					</table>
				)}

				<p className="mt-2 text-xs text-slate-500">
					CTR and CVR are coloured against the account average for the same
					window, not a fixed target: 0.3% CTR is ordinary for a broad discovery
					term and alarming for a branded exact. Hover a cell to see the
					benchmark. The verdict is recomputed from the window totals, so it can
					never contradict the ACOS beside it.
				</p>
			</section>
		</div>
	)
}
