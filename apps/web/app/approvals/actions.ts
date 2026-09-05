"use server"

import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { liveActionSupport } from "@/lib/action-support"

/**
 * Approve or reject a proposed change.
 *
 * The WHERE clause is the policy, not the UI:
 *
 *   status = 'pending'      -- no double-approving, no reviving a rejection
 *   expires_at > now()      -- a 48h-old proposal describes a market that has
 *                              moved; it must be recomputed, not rubber-stamped
 *   action_type <> 'flag'   -- diagnostics are not approvable (ADR 004). The
 *                              database also enforces this via the
 *                              action_flag_is_never_applied constraint in 0006.
 *
 * Zero rows updated is a real answer, and the caller is told which of those
 * three reasons it was. "Nothing happened" with a green tick is how an operator
 * learns not to trust the queue.
 *
 * Attribution follows migration 0009:
 *
 *   decided_by / decided_at / decision   every decision, approve or reject
 *   approved_by / approved_at            approvals only
 *
 * Keeping them separate is the whole point. If a rejection wrote approved_by,
 * then "how many approvals?" would quietly include refusals and "who approved
 * this?" would answer with the name of the person who refused it.
 */

class NotAuthorised extends Error {}
class NothingToDecide extends Error {}

type Decision = "approved" | "rejected"

async function decide(actionId: string, decision: Decision): Promise<void> {
	const { userId, tenantId, role } = await currentContext()
	if (role !== "owner" && role !== "admin") {
		// Applying a change spends real money on a real Amazon account. Without an
		// identity there is nothing to write into the audit trail, and an audit
		// trail with an anonymous actor is not an audit trail.
		throw new NotAuthorised(
			"Only tenant owners and admins can approve Amazon actions.",
		)
	}

	const isApproval = decision === "approved"

	await withTenant(tenantId, async (c) => {
		if (isApproval) {
			const candidate = await query<{ entity_type: string; action_type: string }>(c, "select entity_type, action_type from action where id = $1 and status = 'pending'", [actionId])
			if (candidate.length > 0) {
				const support = liveActionSupport(candidate[0].entity_type, candidate[0].action_type)
				if (!support.supported) throw new NothingToDecide(support.message)
			}
		}
		// $2 feeds both status and decision. That works only because the two
		// vocabularies happen to share these two words right now (0003's status
		// CHECK and 0009's decision CHECK). If either ever gains a value the other
		// lacks, split this into two parameters -- the constraint violation would
		// surface at the worst possible moment, mid-approval.
		const rows = await query<{
			id: string
			entity_type: string
			entity_id: string
			action_type: string
			before_value: unknown
			after_value: unknown
			decided_at: string
		}>(
			c,
			`update action
			    set status      = $2,
			        decision    = $2,
			        decided_by  = $3,
			        decided_at  = now(),
			        approved_by = case when $4::boolean then $3::uuid else approved_by end,
			        approved_at = case when $4::boolean then now() else approved_at end
			  where id = $1
			    and status = 'pending'
			    and expires_at > now()
			    and action_type <> 'flag'
			 returning id, entity_type, entity_id, action_type,
			           before_value, after_value, decided_at::text as decided_at`,
			[actionId, decision, userId, isApproval],
		)

		if (rows.length === 0) {
			// Work out why, so the message is useful. Same transaction, same tenant.
			const existing = await query<{ status: string; expired: boolean; kind: string }>(
				c,
				`select status, (expires_at <= now()) as expired, action_type as kind
				   from action where id = $1`,
				[actionId],
			)
			if (existing.length === 0) {
				throw new NothingToDecide("That action does not exist for this tenant.")
			}
			const e = existing[0]
			if (e.kind === "flag") {
				throw new NothingToDecide(
					"That is a finding, not a proposal. Findings are never applied.",
				)
			}
			if (e.status !== "pending") {
				throw new NothingToDecide(`Already ${e.status}.`)
			}
			if (e.expired) {
				throw new NothingToDecide(
					"Expired. It was computed from older data and must be re-proposed.",
				)
			}
			throw new NothingToDecide("Could not be decided.")
		}

		const a = rows[0]
		await query(
			c,
			`insert into audit_log (tenant_id, actor_user_id, action, entity, before, after)
			 values ($1, $2, $3, $4, $5::jsonb, $6::jsonb)`,
			[
				tenantId,
				userId,
				`action.${decision}`,
				`${a.entity_type}:${a.entity_id}`,
				JSON.stringify({ status: "pending", value: a.before_value }),
				JSON.stringify({
					status: decision,
					decision,
					decided_at: a.decided_at,
					action_type: a.action_type,
					value: a.after_value,
				}),
			],
		)
	})

	// Approval does not touch Amazon. services/actions applies approved rows on
	// its own schedule, captures before_value live at that moment, and fails the
	// action if the live value has drifted from what was shown here.
	revalidatePath("/approvals")
	revalidatePath("/history")
}

export async function approveAction(formData: FormData): Promise<void> {
	await decide(String(formData.get("id")), "approved")
}

export async function rejectAction(formData: FormData): Promise<void> {
	await decide(String(formData.get("id")), "rejected")
}
