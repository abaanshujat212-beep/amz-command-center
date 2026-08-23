"use server"

/**
 * Approve or reject a proposed change.
 *
 * A "use server" module may only export async functions, so everything else
 * here stays private.
 *
 * The policy lives in the WHERE clause, not in the code around it:
 *
 *   status = 'pending'      -- nobody decides twice
 *   expires_at > now()      -- a 48h-old proposal is stale, not merely old;
 *                              the bid it was computed from has moved
 *   action_type <> 'flag'   -- diagnostics are not approvable (ADR 004)
 *
 * Any of those failing updates zero rows, and zero rows is an error the
 * operator sees. The alternative -- checking in TypeScript and then updating --
 * has a gap between the check and the write, and that gap is exactly where two
 * browser tabs approve the same change twice.
 *
 * Two column pairs are written, deliberately:
 *
 *   decided_by / decided_at / decision   every decision, approve or reject
 *   approved_by / approved_at            approvals only
 *
 * Folding rejections into approved_by would have been one character of work and
 * would have made every "how many approvals?" query wrong forever (0009).
 */

import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { canApprove, currentTenantId, currentUserId } from "@/lib/session"

type DecidedRow = {
	id: string
	entity_type: string
	entity_id: string
	action_type: string
	before_value: unknown
	after_value: unknown
}

async function decide(id: string, decision: "approved" | "rejected") {
	if (!id) throw new Error("No action id submitted.")

	// No identity, no decision. An audit trail whose actor is "the system" is
	// not an audit trail, and this action spends a client's money.
	if (!canApprove()) {
		throw new Error(
			"No operator identity is configured, so this decision cannot be " +
				"attributed to anyone. Set DEV_OPERATOR_USER_ID, or wait for real " +
				"authentication.",
		)
	}

	const tenantId = currentTenantId()
	const userId = currentUserId() as string

	await withTenant(tenantId, async (c) => {
		const rows = await query<DecidedRow>(
			c,
			`
			update action
			   set status      = $3,
			       decision    = $3,
			       decided_by  = $2::uuid,
			       decided_at  = now(),
			       approved_by = case when $3 = 'approved' then $2::uuid else approved_by end,
			       approved_at = case when $3 = 'approved' then now()    else approved_at end
			 where id = $1::uuid
			   and status = 'pending'
			   and expires_at > now()
			   and action_type <> 'flag'
			returning id, entity_type, entity_id, action_type, before_value, after_value
			`,
			[id, userId, decision],
		)

		if (rows.length === 0) {
			throw new Error(
				"Nothing was changed. This proposal has already been decided, has " +
					"expired, or is a diagnostic that cannot be approved. Reload the " +
					"queue to see its current state.",
			)
		}

		const r = rows[0]

		// First audit_log writer in the codebase. A decision is the moment a human
		// becomes answerable for a change, so it is the moment worth recording --
		// and a refusal is as much a decision as an approval.
		await query<{ id: string }>(
			c,
			`insert into audit_log (tenant_id, actor_user_id, action, entity, before, after)
			 values ($1::uuid, $2::uuid, $3, $4, $5::jsonb, $6::jsonb)
			 returning id`,
			[
				tenantId,
				userId,
				`action.${decision}`,
				`${r.entity_type}:${r.entity_id}:${r.action_type}`,
				JSON.stringify(r.before_value ?? null),
				JSON.stringify(r.after_value ?? null),
			],
		)
	})

	// Approval does not touch Amazon. services/actions applies it later, under
	// the guardrails, and records the result. Two separate steps on purpose: a
	// slow or failing Amazon API must never make an approval ambiguous.
	revalidatePath("/approvals")
	revalidatePath("/")
}

export async function approveAction(formData: FormData) {
	await decide(String(formData.get("id") ?? ""), "approved")
}

export async function rejectAction(formData: FormData) {
	await decide(String(formData.get("id") ?? ""), "rejected")
}
