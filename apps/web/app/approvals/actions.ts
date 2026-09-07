"use server"

import { revalidatePath } from "next/cache"
import { currentContext } from "@/lib/session"
import { decideAction } from "@/lib/approval-decision"

export async function approveAction(formData: FormData): Promise<void> {
	const actor = await currentContext()
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
