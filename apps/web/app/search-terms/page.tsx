import Link from "next/link"
import { withTenant } from "@/lib/db"
import { acosTone, count, money, percent } from "@/lib/format"
import {
	searchTermPerformance,
	type SearchTermRow,
} from "@/lib/queries-drilldown"
import { ALLOWED_WINDOWS, parseDays, windowHref, type Window } from "@/lib/range"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

/**
 * What a human would do with this row.
 *
 * Wording only. Nothing here writes an action: the rules engine proposes, the
 * approval queue decides, services/actions applies. A second route to Amazon
 * that skipped guardrails, dry-run and audit would make those three things
 * decorative.
 *
 * The thresholds are deliberately coarse. This is a reading aid, not a rule --
 * the real thresholds live in the rule rows, per tenant, and can be tuned
 * without a deploy.
 */
function suggestion(t: SearchTermRow): { text: string; tone: string } {
	const be = t.break_even_acos

	if (t.clicks >= 10 && t.orders === 0) {
		return t.is_already_negative
			? { text: "already negative \u2014 still spending, check the other ad groups", tone: "tone-warn" }
			: { text: "candidate to negate: clicks, no orders", tone: "tone-bad" }
	}
	if (t.orders >= 2 && be !== null && t.acos !== null && t.acos <= be) {
		return t.exists_as_exact
			? { text: "already bid on exactly", tone: "tone-unknown" }
			: { text: "candidate to harvest as exact", tone: "tone-good" }
	}
	if (be !== null && t.acos !== null && t.acos > be * 1.3) {
		return { text: "converting, but above break-even", tone: "tone-warn" }
	}
	if (t.clicks < 10 && t.orders === 0) {
		return { text: "too little data to judge", tone: "tone-unknown" }
	}
	return { text: "\u2014", tone: "tone-unknown" }
}

function WindowPicker({
	days,
	campaign,
}: {
	days: Window
	campaign?: string
}) {
	return (
		<div className="flex gap-1 text-xs">
			{ALLOWED_WINDOWS.map((d) => (
				<Link
					key={d}
					href={windowHref("/search-terms", d, { campaign })}
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

export default async function SearchTerms({
	searchParams,
}: {
	searchParams: Promise<{ days?: string; campaign?: string }>
}) {
	const sp = await searchParams
	const days = parseDays(sp.days)
	const campaign = sp.campaign?.trim() ? sp.campaign.trim() : null
	const tenantId = currentTenantId()

	const terms = await withTenant(tenantId, (c) =>
		searchTermPerformance(c, days, campaign, 200),
	)

	const wasted = terms
		.filter((t) => t.orders === 0)
		.reduce((sum, t) => sum + Number(t.cost ?? 0), 0)

	return (
		<div className="space-y-6">
			<div className="flex flex-wrap items-baseline justify-between gap-3">
				<div>
					<h1 className="text-lg font-semibold">Search terms</h1>
					<div className="text-xs text-slate-500">
						{campaign ? (
							<>
								campaign {campaign} &middot;{" "}
								<Link
									href={`/search-terms?days=${days}`}
									className="text-blue-700 hover:underline"
								>
									show all campaigns
								</Link>
							</>
						) : (
							"all campaigns"
						)}
						{" \u00b7 last "}
						{days} settled days
					</div>
				</div>
				<WindowPicker days={days} campaign={campaign ?? undefined} />
			</div>

			{terms.length === 0 ? (
				<div className="rounded-lg border border-slate-200 bg-white p-8 text-sm text-slate-600">
					<p>No settled search-term rows in this window.</p>
					<p className="mt-2 max-w-2xl">
						Search-term data only exists for keyword-targeted Sponsored Products
						campaigns, and only after the Ads ingest has run. Empty here means no
						data yet, not that customers found you with nothing.
					</p>
				</div>
			) : (
				<>
					{wasted > 0 && (
						<div className="rounded border border-slate-200 bg-white p-3 text-sm">
							<span className="font-medium tabular-nums">{money(wasted)}</span>{" "}
							spent on terms with no attributed orders in this window. Some of that
							is discovery worth paying for; the rest is what the negate rule exists
							to stop.
						</div>
					)}

					<table className="w-full border-collapse bg-white text-sm">
						<thead>
							<tr className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500">
								<th className="px-3 py-2">Search term</th>
								<th className="px-3 py-2">Matched</th>
								<th className="px-3 py-2 text-right">Clicks</th>
								<th className="px-3 py-2 text-right">Spend</th>
								<th className="px-3 py-2 text-right">Orders</th>
								<th className="px-3 py-2 text-right">Sales</th>
								<th className="px-3 py-2 text-right">ACOS</th>
								<th className="px-3 py-2 text-right">CVR</th>
								<th className="px-3 py-2">What to do</th>
							</tr>
						</thead>
						<tbody>
							{terms.map((t) => {
								const s = suggestion(t)
								return (
									<tr
										key={`${t.campaign_id}:${t.ad_group_id}:${t.search_term}`}
										className="border-b border-slate-100 align-top hover:bg-slate-50"
									>
										<td className="px-3 py-2">
											<div className="font-medium">{t.search_term}</div>
											<div className="flex gap-2 text-xs text-slate-500">
												{t.is_already_negative && <span>negative</span>}
												{t.exists_as_exact && <span>exact exists</span>}
											</div>
										</td>
										<td className="px-3 py-2 text-xs text-slate-600">
											{t.matched_keyword_text ?? "\u2014"}
											{t.matched_match_type && (
												<div className="text-slate-400">{t.matched_match_type}</div>
											)}
										</td>
										<td className="num px-3 py-2">{count(t.clicks)}</td>
										<td className="num px-3 py-2">{money(t.cost)}</td>
										<td className="num px-3 py-2">{count(t.orders)}</td>
										<td className="num px-3 py-2">{money(t.sales)}</td>
										<td
											className={`num px-3 py-2 tone-${acosTone(t.acos, t.break_even_acos)}`}
										>
											{percent(t.acos)}
										</td>
										<td className="num px-3 py-2">{percent(t.cvr)}</td>
										<td className={`px-3 py-2 text-xs ${s.tone}`}>{s.text}</td>
									</tr>
								)
							})}
						</tbody>
					</table>

					<p className="text-xs text-slate-500">
						The last column is a reading aid, not a decision. Real thresholds live
						in each tenant&rsquo;s rule rows and can be tuned without a deploy;
						nothing on this page writes to the action table.
					</p>
				</>
			)}
		</div>
	)
}
