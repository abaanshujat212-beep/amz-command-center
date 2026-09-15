import { headers } from "next/headers"
import { auth } from "@/lib/auth"
import {
	assertBusinessHierarchy,
	assertWorkspaceOperation,
	type BusinessContext,
} from "@/lib/business-context"
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
	const context: BusinessContext = {
		workspaceId: session.session.activeWorkspaceId ?? null,
		brandId: session.session.activeBrandId ?? null,
		channelAccountId: session.session.activeChannelAccountId ?? null,
		marketplaceContextId: session.session.activeMarketplaceContextId ?? null,
		adsProfileId: session.session.activeAdsProfileId ?? null,
	}
	if (context.workspaceId) {
		await assertWorkspaceOperation(session.session.token, context.workspaceId, tenantId)
	}
	await assertBusinessHierarchy(tenantId, context)
	return { tenantId, userId: session.user.id, user: session.user, role, ...context }
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
