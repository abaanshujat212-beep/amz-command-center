import Link from "next/link"
import { withTenant } from "@/lib/db"
import { count, money, percent, stamp } from "@/lib/format"
import {
	latestLifecycleRun,
	lifecycleRecommendations,
	parseLifecycleDecision,
	type LifecycleDecision,
	type LifecycleRow,
} from "@/lib/queries-lifecycle"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

type Metrics = Record<string, number | string | null | undefined>
type Evidence = {
	lineage?: Metrics
	destination?: Metrics | null
	source_since_applied?: Metrics
	history?: Metrics
	break_even_cpc?: number
	note?: string
}

const REASONS: Record<string, string> = {
	unsupported_match_type: "destination is not an exact keyword",
	same_ad_group: "source and destination are the same ad group",
	duplicate: "already recommended or an open action exists",
	already_negative: "source already negates this term",
	protected: "term is protected",
	destination_missing: "destination keyword not seen yet",
	destination_inactive: "destination keyword is not enabled",
	destination_no_traffic: "destination not proven yet (too little traffic since promotion)",
	source_no_traffic: "source no longer gets this query",
	recent_traffic: "keyword had clicks recently, not dormant",
	thin_history: "too few historical clicks",
	economics_unknown: "break-even ACOS unknown",
	poor_history: "historical orders or ACOS not good enough",
	bid_unknown: "no historical bid",
	bounds: "safe bid would fall below the tenant minimum",
	cooldown: "changed recently, cooldown active",
}

function num(value: unknown): number | null {
	return typeof value === "number" ? value : value == null || value === "" ? null : Number(value)
}

function Filter({ decision }: { decision: LifecycleDecision | null }) {
	const options: [LifecycleDecision | null, string][] = [
		[null, "all"],
		["recommended", "recommended"],
		["blocked", "blocked"],
	]
	return (
		<div className="flex gap-1 text-xs">
			{options.map(([value, label]) => (
				<Link
					key={label}
					href={value ? `/term-lifecycle?decision=${value}` : "/term-lifecycle"}
					className={
						value === decision
							? "rounded bg-slate-900 px-2 py-1 text-white"
							: "rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-100"
					}
				>
					{label}
				</Link>
			))}
		</div>
	)
}

function Decision({ row }: { row: LifecycleRow }) {
	if (row.decision === "recommended") return <span className="text-xs font-medium tone-good">recommended</span>
	return (
		<div className="text-xs">
			<span className="tone-unknown">blocked</span>
			<div className="text-slate-500">{REASONS[row.blocked_reason ?? ""] ?? row.blocked_reason}</div>
		</div>
	)
}

function IsolationTable({ rows }: { rows: LifecycleRow[] }) {
	return (
		<table className="w-full border-collapse bg-white text-sm">
			<thead>
				<tr className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500">
					<th className="px-3 py-2">Search term</th>
					<th className="px-3 py-2">Negate in (source)</th>
					<th className="px-3 py-2">Promoted to</th>
					<th className="px-3 py-2 text-right">Dest. impr.</th>
					<th className="px-3 py-2 text-right">Dest. clicks</th>
					<th className="px-3 py-2 text-right">Source clicks</th>
					<th className="px-3 py-2 text-right">Source spend</th>
					<th className="px-3 py-2">Decision</th>
				</tr>
			</thead>
			<tbody>
				{rows.map((row) => {
					const ev = row.evidence as Evidence
					const dest = ev.destination ?? {}
					const src = ev.source_since_applied ?? {}
					return (
						<tr key={row.id} className="border-b border-slate-100 align-top hover:bg-slate-50">
							<td className="px-3 py-2">
								<div className="font-medium">{row.term}</div>
								<div className="text-xs text-slate-500">negative exact</div>
							</td>
							<td className="px-3 py-2 text-xs text-slate-600">
								{row.campaign_id}
								<div className="text-slate-400">{row.ad_group_id}</div>
							</td>
							<td className="px-3 py-2 text-xs text-slate-600">
								{ev.lineage?.destination_campaign_id ?? "\u2014"}
								<div className="text-slate-400">
									{ev.lineage?.destination_ad_group_id} &middot; {ev.lineage?.route_code}
								</div>
								<div className="text-slate-400">applied {stamp(ev.lineage?.applied_at as string | null)}</div>
							</td>
							<td className="num px-3 py-2">{count(num(dest.impressions))}</td>
							<td className="num px-3 py-2">{count(num(dest.clicks))}</td>
							<td className="num px-3 py-2">{count(num(src.clicks))}</td>
							<td className="num px-3 py-2">{money(num(src.cost))}</td>
							<td className="px-3 py-2">
								<Decision row={row} />
							</td>
						</tr>
					)
				})}
			</tbody>
		</table>
	)
}

function ReviveTable({ rows }: { rows: LifecycleRow[] }) {
	return (
		<table className="w-full border-collapse bg-white text-sm">
			<thead>
				<tr className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500">
					<th className="px-3 py-2">Paused keyword</th>
					<th className="px-3 py-2">Campaign / ad group</th>
					<th className="px-3 py-2 text-right">Clicks</th>
					<th className="px-3 py-2 text-right">Orders</th>
					<th className="px-3 py-2 text-right">ACOS</th>
					<th className="px-3 py-2 text-right">Break-even</th>
					<th className="px-3 py-2">Last click</th>
					<th className="px-3 py-2 text-right">Last bid</th>
					<th className="px-3 py-2 text-right">Proposed bid</th>
					<th className="px-3 py-2">Decision</th>
				</tr>
			</thead>
			<tbody>
				{rows.map((row) => {
					const h = (row.evidence as Evidence).history ?? {}
					return (
						<tr key={row.id} className="border-b border-slate-100 align-top hover:bg-slate-50">
							<td className="px-3 py-2">
								<div className="font-medium">{row.term}</div>
								<div className="text-xs text-slate-500">
									{row.match_type} &middot; {row.keyword_id}
								</div>
							</td>
							<td className="px-3 py-2 text-xs text-slate-600">
								{row.campaign_id}
								<div className="text-slate-400">{row.ad_group_id}</div>
							</td>
							<td className="num px-3 py-2">{count(num(h.clicks))}</td>
							<td className="num px-3 py-2">{count(num(h.orders))}</td>
							<td className="num px-3 py-2">{percent(num(h.acos))}</td>
							<td className="num px-3 py-2">{percent(num(h.break_even_acos))}</td>
							<td className="px-3 py-2 text-xs text-slate-600">{h.last_click_date ?? "\u2014"}</td>
							<td className="num px-3 py-2">{money(row.current_bid)}</td>
							<td className="num px-3 py-2 font-medium">{money(row.proposed_bid)}</td>
							<td className="px-3 py-2">
								<Decision row={row} />
							</td>
						</tr>
					)
				})}
			</tbody>
		</table>
	)
}

function Section({
	title,
	description,
	rows,
	children,
}: {
	title: string
	description: string
	rows: LifecycleRow[]
	children: React.ReactNode
}) {
	const recommended = rows.filter((r) => r.decision === "recommended").length
	return (
		<section className="space-y-2">
			<div>
				<h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
					{title} ({recommended} recommended &middot; {rows.length - recommended} blocked)
				</h2>
				<p className="max-w-3xl text-xs text-slate-500">{description}</p>
			</div>
			{rows.length === 0 ? (
				<div className="rounded border border-slate-200 bg-white p-4 text-sm text-slate-500">Nothing in this run.</div>
			) : (
				<div className="overflow-x-auto">{children}</div>
			)}
		</section>
	)
}

export default async function TermLifecycle({
	searchParams,
}: {
	searchParams: Promise<{ decision?: string }>
}) {
	const decision = parseLifecycleDecision((await searchParams).decision)
	const tenantId = await currentTenantId()
	const { run, rows } = await withTenant(tenantId, async (client) => {
		const run = await latestLifecycleRun(client)
		return { run, rows: run ? await lifecycleRecommendations(client, run.run_id, null, decision) : [] }
	})
	const isolation = rows.filter((r) => r.recommendation_type === "isolation_negative")
	const revive = rows.filter((r) => r.recommendation_type === "revive_target")

	return (
		<div className="space-y-6">
			<div className="flex flex-wrap items-baseline justify-between gap-3">
				<div>
					<h1 className="text-lg font-semibold">Search-term isolation &amp; revive</h1>
					<div className="text-xs text-slate-500">
						{run
							? `latest run ${stamp(run.created_at)} \u00b7 data through ${run.data_through}`
							: "no run yet"}
					</div>
				</div>
				<Filter decision={decision} />
			</div>

			<div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
				<b>Recommendations only.</b> Nothing on this page creates an action or changes Amazon. Applying a
				negative or a bid still goes through the rules engine, approval queue, guardrails and audit.
			</div>

			{!run ? (
				<div className="rounded-lg border border-slate-200 bg-white p-8 text-sm text-slate-600">
					<p>No isolation or revive analysis has been run for this account yet.</p>
					<p className="mt-2 font-mono text-xs">python -m services.rules.isolation_revive --tenant-id &lt;tenant-id&gt;</p>
				</div>
			) : (
				<>
					<Section
						title="Isolation negatives"
						description="A harvested term that is now live in its exact destination keeps matching in the source ad group. Negating it there is only recommended once the destination is enabled and has proven traffic since the promotion."
						rows={isolation}
					>
						<IsolationTable rows={isolation} />
					</Section>
					<Section
						title="Revive targets"
						description="Paused keywords that converted under break-even and have been dormant. The proposed bid is the last bid, capped at the break-even CPC and kept inside tenant bid bounds."
						rows={revive}
					>
						<ReviveTable rows={revive} />
					</Section>
				</>
			)}
		</div>
	)
}
