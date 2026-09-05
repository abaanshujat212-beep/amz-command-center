import { withTenant } from "@/lib/db"
import { money } from "@/lib/format"
import { pendingActions, type PendingAction } from "@/lib/queries"
import { canApprove, currentTenantId } from "@/lib/session"
import { approveAction, rejectAction } from "./actions"
import { liveActionSupport } from "@/lib/action-support"

export const dynamic = "force-dynamic"

/** Proposals carry {"value": n}; diagnostics carry {"value": null}. */
function shown(v: unknown): string {
	if (v === null || v === undefined) return "\u2014"
	if (typeof v === "object" && v !== null && "value" in v) {
		const inner = (v as { value: unknown }).value
		if (inner === null || inner === undefined) return "\u2014"
		if (typeof inner === "number") return String(inner)
		return String(inner)
	}
	return typeof v === "string" ? v : JSON.stringify(v)
}

const MONEY_ACTIONS = new Set(["set_bid", "set_budget"])

function Value({ raw, type }: { raw: unknown; type: string }) {
	const text = shown(raw)
	if (text === "\u2014") return <span className="text-slate-400">unknown</span>
	const n = Number(text)
	if (MONEY_ACTIONS.has(type) && Number.isFinite(n)) return <>{money(n)}</>
	return <>{text}</>
}

function hoursLeft(expiresAt: string): number {
	return Math.max(
		0,
		Math.round((new Date(expiresAt).getTime() - Date.now()) / 3_600_000),
	)
}

function Row({ a, armed }: { a: PendingAction; armed: boolean }) {
	const left = hoursLeft(a.expires_at)
	const live = liveActionSupport(a.entity_type, a.action_type)
	return (
		<li className="rounded-lg border border-slate-200 bg-white p-4">
			<div className="flex flex-wrap items-start justify-between gap-4">
				<div className="min-w-0">
					<div className="text-sm font-medium">
						{a.action_type}
						<span className="ml-2 font-normal text-slate-500">
							{a.entity_type} {a.entity_id}
						</span>
					</div>

					<div className="mt-1 text-sm tabular-nums">
						<Value raw={a.before_value} type={a.action_type} />
						<span className="mx-2 text-slate-400">&rarr;</span>
						<span className="font-medium">
							<Value raw={a.after_value} type={a.action_type} />
						</span>
					</div>

					{a.reason_text && (
						<p className="mt-1 text-sm text-slate-600">{a.reason_text}</p>
					)}

					{a.clamped && (
						<p className="mt-1 text-xs text-warn">
							Clamped by a guardrail: {a.clamp_note}
						</p>
					)}
					<p className={`mt-1 text-xs ${live.supported ? "tone-good" : "tone-warn"}`}>{live.supported ? "Live path verified" : "Live apply blocked"} · {live.message}</p>

					<div className="mt-2 text-xs text-slate-500">
						{a.rule_name ?? a.rule_code ?? "manual"} &middot; expires in {left}h
					</div>
				</div>

				<div className="flex shrink-0 gap-2">
					<form action={approveAction}>
						<input type="hidden" name="id" value={a.id} />
						<button
							type="submit"
							disabled={!armed || !live.supported}
							className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:bg-slate-300"
						>
							Approve
						</button>
					</form>
					<form action={rejectAction}>
						<input type="hidden" name="id" value={a.id} />
						<button
							type="submit"
							disabled={!armed}
							className="rounded border border-slate-300 px-3 py-1.5 text-sm disabled:text-slate-400"
						>
							Reject
						</button>
					</form>
				</div>
			</div>
		</li>
	)
}

export default async function Approvals() {
	const tenantId = await currentTenantId()
	const actions = await withTenant(tenantId, (c) => pendingActions(c, 100))
	const armed = await canApprove()

	return (
		<div className="space-y-4">
			<div className="flex items-baseline justify-between">
				<h1 className="text-lg font-semibold">Approval queue</h1>
				<span className="text-xs text-slate-500">{actions.length} pending</span>
			</div>

			{!armed && (
				<div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">
					Read-only: your tenant role cannot approve Amazon changes. Ask the owner
					to assign the Admin role if approval access is required.
				</div>
			)}

			{actions.length === 0 ? (
				<div className="rounded-lg border border-slate-200 bg-white p-8 text-sm text-slate-600">
					<p>Nothing waiting.</p>
					<p className="mt-2 max-w-2xl">
						An empty queue means one of three things, and they are worth
						distinguishing: the rules engine has not run, every rule is still
						disabled and in dry-run (the shipped default), or nothing currently
						meets a rule&rsquo;s thresholds.
					</p>
					<p className="mt-2 max-w-2xl">
						Proposals also expire after 48 hours rather than waiting
						indefinitely, because a bid change that made sense on Monday&rsquo;s
						data can be wrong by Wednesday.
					</p>
				</div>
			) : (
				<ul className="space-y-3">
					{actions.map((a) => (
						<Row key={a.id} a={a} armed={armed} />
					))}
				</ul>
			)}

			<p className="text-xs text-slate-500">
				Approving does not touch Amazon. The action worker applies approved rows
				later, reads the live value at that moment, and fails the action if it
				has drifted from what is shown here.
			</p>
		</div>
	)
}
