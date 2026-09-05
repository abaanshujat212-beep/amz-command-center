import { headers } from "next/headers"
import { auth } from "@/lib/auth"
import { assertMembership, CAN_APPROVE, type TenantRole } from "@/lib/db"

export class AuthenticationRequired extends Error {
	constructor() { super("Please sign in to continue.") }
}

export class TenantSelectionRequired extends Error {
	constructor() { super("Select a tenant before opening the dashboard.") }
}

export async function currentContext() {
	const session = await auth.api.getSession({ headers: await headers() })
	if (!session) throw new AuthenticationRequired()
	const tenantId = session.session.activeTenantId
	if (!tenantId) throw new TenantSelectionRequired()
	const role: TenantRole = await assertMembership(tenantId, session.user.id)
	return { tenantId, userId: session.user.id, user: session.user, role }
}

export async function currentTenantId(): Promise<string> {
	return (await currentContext()).tenantId
}

export async function currentUserId(): Promise<string> {
	return (await currentContext()).userId
}

export async function canApprove(): Promise<boolean> {
	return CAN_APPROVE.has((await currentContext()).role)
}
