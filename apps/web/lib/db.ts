/**
 * Tenant-scoped database access.
 *
 * Every query MUST go through withTenant(). It opens a transaction and sets
 * app.tenant_id before running anything, which is what activates the Row Level
 * Security policies in packages/db/migrations/0002_rls.sql.
 *
 * Do not export the raw pool. A query without tenant context returns zero rows
 * by design, but bypassing this helper is still treated as a bug.
 */

import { Pool, type PoolClient } from "pg"

const pool = new Pool({
	connectionString: process.env.DATABASE_URL,
	max: 10,
})

export class TenantContextMissing extends Error {
	constructor() {
		super("No tenant id provided. Refusing to query without tenant context.")
	}
}

export async function withTenant<T>(
	tenantId: string | null | undefined,
	fn: (client: PoolClient) => Promise<T>,
): Promise<T> {
	if (!tenantId) throw new TenantContextMissing()

	const client = await pool.connect()
	try {
		await client.query("begin")
		// transaction-local: cannot leak to the next user of this pooled connection
		await client.query("select set_tenant($1)", [tenantId])
		const result = await fn(client)
		await client.query("commit")
		return result
	} catch (err) {
		await client.query("rollback")
		throw err
	} finally {
		client.release()
	}
}

/** Verify membership before trusting a tenant id from a session or a request. */
export async function assertMembership(
	tenantId: string,
	userId: string,
): Promise<"owner" | "admin" | "analyst" | "viewer"> {
	return withTenant(tenantId, async (client) => {
		const { rows } = await client.query<{ role: string }>(
			"select role from tenant_member where tenant_id = $1 and user_id = $2",
			[tenantId, userId],
		)
		if (rows.length === 0) throw new Error("not a member of this tenant")
		return rows[0].role as "owner" | "admin" | "analyst" | "viewer"
	})
}

/** Roles allowed to approve or apply changes on a live Amazon account. */
export const CAN_APPROVE = new Set(["owner", "admin"])
