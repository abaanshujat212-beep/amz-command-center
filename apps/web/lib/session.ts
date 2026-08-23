/**
 * TEMPORARY tenant + identity resolution.
 *
 * Better Auth (organisation plugin) is the decided path and is not built yet.
 * Until it is, identity comes from the environment: correct for one operator on
 * one machine, unacceptable the moment a client logs in.
 *
 * The one thing this shim must never do is guess. "Pick the first tenant" is
 * how a single-tenant assumption survives into a multi-tenant product, and it
 * fails by showing someone else's data rather than by crashing.
 */

export class NoTenantConfigured extends Error {
	constructor() {
		super(
			"DEV_TENANT_ID is not set. Run `make seed` and copy the tenant id into " +
				".env. This shim will not choose a tenant for you.",
		)
	}
}

export function currentTenantId(): string {
	const id = process.env.DEV_TENANT_ID
	if (!id) throw new NoTenantConfigured()
	return id
}

/**
 * Who is acting. Written into action.approved_by, so it has to be a real uuid
 * or nothing at all -- an audit trail with a placeholder actor is not an audit
 * trail.
 */
export function currentUserId(): string | null {
	return process.env.DEV_OPERATOR_USER_ID ?? null
}

/**
 * Approving a change means real money moves on a real Amazon account. Without
 * an identity we cannot record who authorised it, so we do not allow it.
 */
export function canApprove(): boolean {
	return currentUserId() !== null
}

export const AUTH_IS_A_SHIM = true
