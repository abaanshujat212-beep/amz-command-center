import { withTenant } from "@/lib/db"
import { money } from "@/lib/format"
import { pendingActions, type PendingAction } from "@/lib/queries"
import { canApprove, currentTenantId } from "@/lib/session"
import { approveAction, rejectAction } from "./actions"

export const dynamic = "force-dynamic"

/** Engine writes {"value": <n>, ...}; older rows may hold a bare number. */
function readValue(v: unknown): number | null {
	if (v === null || v === undefined) return null
	if (typeof v === "number") return v
	if (typeof v === "object" && "value" in (v as Record<string, unknown>)) {
		const inner = (v as Record<string, unknown>).value
		return typeof inner === "number" ? inner : null
	}
	return null
}

const MONEY_ACTIONS = new Set(["set_bid", "set_budget"])

function Change({ row }: { row: PendingAction }) {
	const before = readValue(row.before_value)
	const after = readValue(row.after_value)
	const fmt = (n: number | null) =>
		n === null
			? "?"
			: MONEY_ACTIONS.has(row.action_type)
				? money(n)
				: String(n)

	if (before === null && after === null) {
		return <span className="text-slate-500">{row.action_type}</span>
	}

	const pct =
		before !== null && after !== null && before !== 0
			? Math.round(((after - before) / before) * 100)
			: null

	return (
		<span className="tabular-nums">
			{fmt(before)} &rarr; <span className="font-medium">{fmt(after)}</span>
			{pct !== null && (
				<span className="ml-1 text-xs text-slate-500">
					({pct > 0 ? "+" : ""}
					{pct}%)
				</span>
			)}
		</span>
	)
}

function hoursLeft(expiresAt: string): number {
	return Math.max(
		0,
		Math.round((new Date(expiresAt).getTime() - Date.now()) / 3_600_000),
	)
}

export default async function Approvals() {
	const tenantId = currentTenantId()
	const rows = await withTenant(tenantId, (c) => pendingActions(c, 200))
	const allowed = canApprove()

	return (
		<div className="space-y-4">
			<div className="flex items-baseline justify-between">
				<h1 className="text-lg font-semibold">Approval queue</h1>
				<span className="text-xs text-slate-500">
					{rows.length} waiting &middot; proposals expire 48h after they are made
				</span>
			</div>

			{!allowed && (
				<p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm">
					Read-only: no operator identity is configured, so a decision could not
					be attributed to anyone. Approving spends real money on a live Amazon
					account, so it stays disabled until authentication exists.
				</p>
			)}

			{rows.length === 0 ? (
				<div className="rounded-lg border border-slate-200 bg-white p-8 text-sm text-slate-600">
					<p className="font-medium text-slate-900">Nothing waiting.</p>
					<p className="mt-2 max-w-2xl">
						An empty queue is the normal state while rules are in dry run: they
						write an evaluation for every match and an action for none of them.
						That is the intended sequence &mdash; two weeks of watching what the
						rules would have done comes before they are allowed to do it.
					</p>
				</div>
			) : (
				<ul className="space-y-3">
					{rows.map((row) => (
						<li
							key={row.id}
							className="rounded-lg border border-slate-200 bg-white p-4"
						>
							<div className="flex flex-wrap items-start justify-between gap-4">
								<div className="min-w-0">
									<div className="text-sm">
										<span className="font-medium">{row.action_type}</span>
										<span className="text-slate-500">
											{" "}
											&middot; {row.entity_type} {row.entity_id}
										</span>
									</div>
									<div className="mt-1 text-base">
										<Change row={row} />
									</div>
									<div className="mt-1 text-sm text-slate-700">
										{row.reason_text ?? "No reason recorded."}
									</div>
									<div className="mt-1 text-xs text-slate-500">
										{row.rule_name ?? row.rule_code ?? "manual"} &middot; expires
										in {hoursLeft(row.expires_at)}h
									</div>
									{row.clamped && (
										<div className="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">
											Clamped by a guardrail: {row.clamp_note}. The rule asked for
											more than this.
										</div>
									)}
								</div>

								<div className="flex shrink-0 gap-2">
									<form action={approveAction}>
										<input type="hidden" name="id" value={row.id} />
										<button
											type="submit"
											disabled={!allowed}
											className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:bg-slate-300"
										>
											Approve
										</button>
									</form>
									<form action={rejectAction}>
										<input type="hidden" name="id" value={row.id} />
										<button
											type="submit"
											disabled={!allowed}
											className="rounded border border-slate-300 px-3 py-1.5 text-sm disabled:text-slate-400"
										>
											Reject
										</button>
									</form>
								</div>
							</div>
						</li>
					))}
				</ul>
			)}

			<p className="text-xs text-slate-500">
				Approving does not contact Amazon. It marks the change as authorised;
				the action service applies it, re-reads the live value first, and fails
				the action if someone changed it in the meantime.
			</p>
		</div>
	)
}
