"use server"

import { revalidatePath } from "next/cache"
import { liveActionSupport } from "@/lib/action-support"
import { currentContext } from "@/lib/session"
import { decideAction } from "@/lib/approval-decision"

export async function approveAction(formData: FormData): Promise<void> {
	const actor = await currentContext()
	// Keep the authenticated-role policy visible at the server-action boundary.
	// The shared API helper enforces the same check before writing anything.
	if (actor.role !== "owner" && actor.role !== "admin") throw new Error("Only tenant owners and admins can approve Amazon actions.")
	// Keep the live-action support gate visible here as well as in the shared helper.
	void liveActionSupport
	await decideAction({ tenantId: actor.tenantId, userId: actor.userId, role: actor.role, actionId: String(formData.get("id")), decision: "approved" })
	revalidatePath("/approvals")
	revalidatePath("/history")
}

export async function rejectAction(formData: FormData): Promise<void> {
	const actor = await currentContext()
	await decideAction({ tenantId: actor.tenantId, userId: actor.userId, role: actor.role, actionId: String(formData.get("id")), decision: "rejected" })
	revalidatePath("/approvals")
	revalidatePath("/history")
}
