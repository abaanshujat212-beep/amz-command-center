"use server"

import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { canApprove, currentTenantId, currentUserId } from "@/lib/session"

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
 */

export class NotAuthorised extends Error {}
export class NothingToDecide extends Error {}

type Decision = "approved" | "rejected"

async function decide(actionId: string, decision: Decision): Promise<void> {
	const userId = currentUserId()
	if (!canApprove() || userId === null) {
		// Applying a change spends real money on a real Amazon account. Without an
		// identity there is nothing to write into the audit trail, and an audit
		// trail with an anonymous actor is not an audit trail.
		throw new NotAuthorised(
			"No operator identity. Set DEV_OPERATOR_USER_ID, or wait for auth.",
		)
	}

	const tenantId = currentTenantId()

	await withTenant(tenantId, async (c) => {
		// approved_by is written for both outcomes today because the schema has no
		// rejected_by. See the note on #22.
		const rows = await query<{
			id: string
			entity_type: string
			entity_id: string
			action_type: string
			before_value: unknown
			after_value: unknown
		}>(
			c,
			`update action
			    set status = $2,
			        approved_by = $3,
			        approved_at = now()
			  where id = $1
			    and status = 'pending'
			    and expires_at > now()
			    and action_type <> 'flag'
			 returning id, entity_type, entity_id, action_type,
			           before_value, after_value`,
			[actionId, decision, userId],
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
}

export async function approveAction(formData: FormData): Promise<void> {
	await decide(String(formData.get("id")), "approved")
}

export async function rejectAction(formData: FormData): Promise<void> {
	await decide(String(formData.get("id")), "rejected")
}
