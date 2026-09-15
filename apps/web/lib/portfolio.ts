import { authPool } from "@/lib/auth"
import { query, withTenant } from "@/lib/db"
import { accountTotals, automationState, dataFreshness, openAlerts, pendingActions, tenantIdentity } from "@/lib/queries"

export type Availability = "AVAILABLE" | "NO_DATA" | "STALE" | "BLOCKED" | "WAITING_FOR_AUTHORIZATION" | "EXTERNAL_ACCESS_REQUIRED"
type Membership = { tenant_id: string; name: string; slug: string; role: string }

type AccountSummary = {
	tenantId: string
	name: string
	slug: string
	role: string
	currency: string | null
	marketplace: string | null
	state: Availability
	dataThrough: string | null
	freshnessHours: number | null
	sales: number | null
	spend: number | null
	acos: number | null
	pendingApprovals: number
	openAlerts: number
	failedActions: number
	deadLetterActions: number
	automationEnabled: boolean
	dryRun: boolean
	inventory: { state: Availability; value: null }
	contributionProfit: { state: Availability; value: null }
}

async function authorizedTenants(token: string, workspaceId: string, requireAlerts: boolean): Promise<Membership[]> {
	const { rows } = await authPool.query<Membership>(
		"select * from public.session_workspace_portfolio_tenants($1,$2,$3)",
		[token, workspaceId, requireAlerts],
	)
	return rows
}

async function summarizeTenant(membership: Membership): Promise<AccountSummary> {
	return withTenant(membership.tenant_id, async client => {
		const [identity, totals, freshness, approvals, alerts, automation, actionCounts] = await Promise.all([
			tenantIdentity(client), accountTotals(client), dataFreshness(client), pendingActions(client, 500),
			openAlerts(client, 500), automationState(client),
			query<{ failed: number; dead_letter: number }>(client, "select count(*) filter(where status='failed')::int as failed,count(*) filter(where status='dead_letter')::int as dead_letter from action"),
		])
		const measured = freshness.filter(item => item.hours_old !== null)
		const freshnessHours = measured.length ? Math.max(...measured.map(item => item.hours_old as number)) : null
		const state: Availability = totals?.data_through == null ? "NO_DATA" : freshnessHours != null && freshnessHours > 48 ? "STALE" : "AVAILABLE"
		return {
			tenantId: membership.tenant_id, name: membership.name, slug: membership.slug, role: membership.role,
			currency: identity?.currency ?? automation?.currency ?? null, marketplace: identity?.country_code ?? null,
			state, dataThrough: totals?.data_through ?? null, freshnessHours,
			sales: totals?.data_through ? totals.sales : null, spend: totals?.data_through ? totals.cost : null,
			acos: totals?.data_through ? totals.acos : null, pendingApprovals: approvals.length,
			openAlerts: alerts.length, failedActions: actionCounts[0]?.failed ?? 0,
			deadLetterActions: actionCounts[0]?.dead_letter ?? 0,
			automationEnabled: automation?.automation_enabled ?? false, dryRun: automation?.dry_run ?? true,
			inventory: { state: "NO_DATA", value: null }, contributionProfit: { state: "NO_DATA", value: null },
		}
	})
}

export async function portfolioSummary(token: string, workspaceId: string, page: number, pageSize: number, requireAlerts = false) {
	const authorized = await authorizedTenants(token, workspaceId, requireAlerts)
	const start = (page - 1) * pageSize
	const accounts = await Promise.all(authorized.slice(start, start + pageSize).map(summarizeTenant))
	const aggregates = new Map<string, { currency: string; sales: number; spend: number; accountCount: number }>()
	for (const account of accounts) {
		if (account.state === "NO_DATA" || !account.currency || account.sales == null || account.spend == null) continue
		const current = aggregates.get(account.currency) ?? { currency: account.currency, sales: 0, spend: 0, accountCount: 0 }
		current.sales += account.sales; current.spend += account.spend; current.accountCount += 1
		aggregates.set(account.currency, current)
	}
	return {
		workspaceId, page, pageSize, total: authorized.length, accounts,
		coverage: { returned: accounts.length, withPerformanceData: accounts.filter(a => a.state !== "NO_DATA").length },
		aggregates: [...aggregates.values()].map(value => ({ ...value, acos: value.sales > 0 ? value.spend / value.sales : null })),
	}
}
