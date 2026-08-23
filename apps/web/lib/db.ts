/**
 * Tenant-scoped database access.
 *
 * Every query MUST go through withTenant(). It opens a transaction and sets
 * app.tenant_id before running anything, which is what activates the Row Level
 * Security policies in packages/db/migrations/0002_rls.sql.
 *
 * Do not export the raw pool. A query without tenant context returns zero rows
 * by design, but bypassing this helper is still treated as a bug.
 *
 * Two rules that are easy to get wrong, and were:
 *
 *   1. Connect as axaty_app, never as the owner. Public tables are protected
 *      either way, because 0002/0003 set FORCE ROW LEVEL SECURITY. The marts
 *      schema is not protected at all, and the owner can read all of it.
 *
 *   2. Read marts only through the copilot.* views (0007, 0008). They carry the
 *      tenant filter inside the view definition, so it cannot be forgotten.
 *      axaty_app holds no privilege on marts, so this is enforced by the
 *      database rather than by remembering.
 */

import { Pool, type PoolClient, type QueryResultRow } from "pg"

/** Schema holding tenant-filtered views over the dbt marts. */
export const MART_SCHEMA = "copilot"

/** copilot."mart_ppc_campaign_daily" -- use this instead of writing marts.* */
export function mart(name: string): string {
	if (!/^[a-z_][a-z0-9_]*$/.test(name)) {
		throw new Error(`suspicious mart name: ${name}`)
	}
	return `${MART_SCHEMA}."${name}"`
}

function connectionString(): string {
	const appUrl = process.env.DATABASE_URL_APP
	if (!appUrl) {
		throw new Error(
			"DATABASE_URL_APP is not set. The dashboard must connect as axaty_app, " +
				"not as the owner role. See .env.example.",
		)
	}
	// The owner bypasses nothing on public tables (FORCE RLS) but can read every
	// tenant's rows in marts, which have no RLS. Fail loudly rather than serve
	// one client another client's numbers.
	if (appUrl === process.env.DATABASE_URL) {
		throw new Error(
			"DATABASE_URL_APP is the owner connection string. Create the axaty_app " +
				"login and point DATABASE_URL_APP at it.",
		)
	}
	return appUrl
}

let _pool: Pool | null = null

function pool(): Pool {
	// Lazy, so importing this module during a build does not require a database.
	if (_pool === null) {
		_pool = new Pool({ connectionString: connectionString(), max: 10 })
	}
	return _pool
}

export class TenantContextMissing extends Error {
	constructor() {
		super("No tenant id provided. Refusing to query without tenant context.")
	}
}

export class UnsafeMartAccess extends Error {
	constructor(sql: string) {
		super(
			`This query reads marts directly, which has no row-level security. ` +
				`Use ${MART_SCHEMA}.<mart_name> instead: ${sql.slice(0, 120)}`,
		)
	}
}

export async function withTenant<T>(
	tenantId: string | null | undefined,
	fn: (client: PoolClient) => Promise<T>,
): Promise<T> {
	if (!tenantId) throw new TenantContextMissing()

	const client = await pool().connect()
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

/**
 * Run a query inside a tenant transaction.
 *
 * The marts check is a developer aid, not a security boundary -- axaty_app has
 * no privilege on marts, so the database would refuse anyway. The point is to
 * fail with a sentence explaining what to do instead, rather than with
 * "permission denied for schema marts" three layers down a stack trace.
 */
export async function query<T extends QueryResultRow>(
	client: PoolClient,
	sql: string,
	params: unknown[] = [],
): Promise<T[]> {
	if (/\bmarts\s*\./i.test(sql)) throw new UnsafeMartAccess(sql)
	const { rows } = await client.query<T>(sql, params)
	return rows
}

/** Verify membership before trusting a tenant id from a session or a request. */
export async function assertMembership(
	tenantId: string,
	userId: string,
): Promise<"owner" | "admin" | "analyst" | "viewer"> {
	return withTenant(tenantId, async (client) => {
		const rows = await query<{ role: string }>(
			client,
			"select role from tenant_member where tenant_id = $1 and user_id = $2",
			[tenantId, userId],
		)
		if (rows.length === 0) throw new Error("not a member of this tenant")
		return rows[0].role as "owner" | "admin" | "analyst" | "viewer"
	})
}

/** Roles allowed to approve or apply changes on a live Amazon account. */
export const CAN_APPROVE = new Set(["owner", "admin"])
