import Link from "next/link"
import { isMoneyAction, shown } from "@/lib/action-value"
import { withTenant } from "@/lib/db"
import { money, stamp } from "@/lib/format"
import {
	actionHistory,
	historyTotals,
	type HistoryRow,
} from "@/lib/queries-drilldown"
import { ALLOWED_WINDOWS, parseDays, windowHref, type Window } from "@/lib/range"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

/**
 * Statuses a row can currently reach.
 *
 * Nothing applies actions yet -- services/actions has a state machine but no
 * worker (#23). So applied / verified / failed / rolled_back are unreachable
 * today, and the screen says so rather than presenting an empty applied column
 * as a clean track record.
 */
const REACHABLE_TODAY = new Set(["approved", "rejected", "expired"])

function statusTone(status: string): string {
	if (status === "applied" || status === "verified") return "tone-good"
	if (status === "failed" || status === "rolled_back") return "tone-bad"
	if (status === "approved") return "tone-warn"
	return "tone-unknown"
}

function Side({ raw, type }: { raw: unknown; type: string }) {
	const text = shown(raw)
	if (text === null) return <span className="text-slate-400">unknown</span>
	const n = Number(text)
	if (isMoneyAction(type) && Number.isFinite(n)) return <>{money(n)}</>
	return <>{text}</>
}

function WindowPicker({ days }: { days: Window }) {
	return (
		<div className="flex gap-1 text-xs">
			{ALLOWED_WINDOWS.map((d) => (
				<Link
					key={d}
					href={windowHref("/history", d)}
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

function Outcome({ row }: { row: HistoryRow }) {
	if (row.status === "failed" && row.error) {
		const drift = row.error.startsWith("drift:")
		return (
			<div className="text-xs">
				<span className={drift ? "text-warn" : "text-bad"}>
					{drift ? "refused: value had drifted" : "failed"}
				</span>
				<div className="text-slate-500">{row.error}</div>
			</div>
		)
	}
	if (row.outcome) {
		return <span className="text-xs text-slate-600">{row.outcome}</span>
	}
	if (row.status === "applied") {
		return (
			<span className="text-xs text-slate-500" title="Verified 7 days after apply">
				awaiting verification
			</span>
		)
	}
	return <span className="text-xs text-slate-400">&mdash;</span>
}

export default async function History({
	searchParams,
}: {
	searchParams: Promise<{ days?: string }>
}) {
	const sp = await searchParams
	const days = parseDays(sp.days)
	const tenantId = currentTenantId()

	const { rows, totals } = await withTenant(tenantId, async (c) => ({
		rows: await actionHistory(c, days, 200),
		totals: await historyTotals(c, days),
	}))

	const appliedSpend = totals
		.filter((t) => t.spend_delta !== null)
		.reduce((sum, t) => sum + Number(t.spend_delta ?? 0), 0)

	const unreachable = totals.filter((t) => !REACHABLE_TODAY.has(t.status))

	return (
		<div className="space-y-6">
			<div className="flex flex-wrap items-baseline justify-between gap-3">
				<h1 className="text-lg font-semibold">Decision history</h1>
				<WindowPicker days={days} />
			</div>

			<div className="flex flex-wrap gap-2 text-xs">
				{totals.length === 0 ? (
					<span className="text-slate-500">Nothing decided in this window.</span>
				) : (
					totals.map((t) => (
						<span
							key={t.status}
							className={`rounded border border-slate-200 bg-white px-2 py-1 ${statusTone(t.status)}`}
						>
							{t.status} <span className="tabular-nums">{t.n}</span>
						</span>
					))
				)}
				{appliedSpend !== 0 && (
					<span className="rounded border border-slate-200 bg-white px-2 py-1">
						applied bid/budget delta{" "}
						<span className="tabular-nums">{money(appliedSpend)}</span>
					</span>
				)}
			</div>

			{unreachable.length === 0 && (
				<div className="rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
					No row here has been applied, failed or rolled back, and none can be
					yet: nothing sends changes to Amazon. The action worker and the T+7
					verification pass are issue #23. Until then this screen shows approvals,
					rejections and expiries only &mdash; an empty{" "}
					<code>applied</code> column here is an unwritten worker, not a clean
					record.
				</div>
			)}

			{rows.length === 0 ? (
				<div className="rounded-lg border border-slate-200 bg-white p-8 text-sm text-slate-600">
					<p>No decisions in the last {days} days.</p>
					<p className="mt-2 max-w-2xl">
						That is the expected state while every rule ships disabled and in
						dry-run: no proposals are generated, so there is nothing to decide.
						Rejections and expiries would show here too, so an empty list does
						not mean approvals are being lost.
					</p>
					<Link
						href="/approvals"
						className="mt-3 inline-block text-blue-700 hover:underline"
					>
						Open the approval queue &rarr;
					</Link>
				</div>
			) : (
				<table className="w-full border-collapse bg-white text-sm">
					<thead>
						<tr className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500">
							<th className="px-3 py-2">Decided</th>
							<th className="px-3 py-2">Change</th>
							<th className="px-3 py-2">Status</th>
							<th className="px-3 py-2">Applied</th>
							<th className="px-3 py-2">Result</th>
							<th className="px-3 py-2">Rule</th>
						</tr>
					</thead>
					<tbody>
						{rows.map((row) => (
							<tr key={row.id} className="border-b border-slate-100 align-top">
								<td className="px-3 py-2 whitespace-nowrap">
									<div>{stamp(row.decided_at ?? row.sort_at)}</div>
									{row.decided_at === null && (
										<div
											className="text-xs text-slate-400"
											title="No human decision was recorded; this is the request time"
										>
											proposed
										</div>
									)}
								</td>
								<td className="px-3 py-2">
									<div className="font-medium">{row.action_type}</div>
									<div className="text-xs text-slate-500">
										{row.entity_type} {row.entity_id}
									</div>
									<div className="mt-1 tabular-nums">
										<Side raw={row.before_value} type={row.action_type} />
										<span className="mx-2 text-slate-400">&rarr;</span>
										<span className="font-medium">
											<Side raw={row.after_value} type={row.action_type} />
										</span>
									</div>
								</td>
								<td className={`px-3 py-2 ${statusTone(row.status)}`}>
									{row.status}
									{row.decision !== null && row.decision !== row.status && (
										<div className="text-xs text-slate-500">
											decided: {row.decision}
										</div>
									)}
								</td>
								<td className="px-3 py-2 whitespace-nowrap text-xs text-slate-600">
									{row.applied_at ? stamp(row.applied_at) : "\u2014"}
									{row.rolled_back_at && (
										<div className="text-bad">
											rolled back {stamp(row.rolled_back_at)}
										</div>
									)}
								</td>
								<td className="px-3 py-2">
									<Outcome row={row} />
								</td>
								<td className="px-3 py-2 text-xs text-slate-500">
									{row.rule_name ?? row.rule_code ?? "manual"}
									{row.reason_text && (
										<div className="text-slate-600">{row.reason_text}</div>
									)}
								</td>
							</tr>
						))}
					</tbody>
				</table>
			)}

			<p className="text-xs text-slate-500">
				Every decision is attributed: <code>decided_by</code> /{" "}
				<code>decided_at</code> cover approvals and rejections alike, while{" "}
				<code>approved_by</code> stays approval-only so approval counts never
				quietly include refusals (migration <code>0009</code>).
			</p>
		</div>
	)
}
