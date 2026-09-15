import type { AccountSummary, Availability } from "@/lib/portfolio"

export type AttentionSeverity = "CRITICAL" | "HIGH" | "MEDIUM"
export type AttentionReason = "DEAD_LETTER_ACTIONS" | "FAILED_ACTIONS" | "OPEN_ALERTS" | "STALE_DATA" | "NO_PERFORMANCE_DATA" | "ACOS_ABOVE_TARGET" | "PENDING_APPROVALS"
export type AttentionItem = {
	tenantId: string
	tenantName: string
	severity: AttentionSeverity
	reason: AttentionReason
	sourceState: Availability
	observedAt: string | null
	drillDownRoute: string
	count: number | null
	actual: number | null
	threshold: number | null
}

const priority: Record<AttentionSeverity, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2 }

function item(account: AccountSummary, severity: AttentionSeverity, reason: AttentionReason, route: string, observedAt: string | null, count: number | null = null, actual: number | null = null, threshold: number | null = null): AttentionItem {
	return { tenantId: account.tenantId, tenantName: account.name, severity, reason, sourceState: account.state, observedAt, drillDownRoute: route, count, actual, threshold }
}

export function buildPortfolioAttention(accounts: AccountSummary[]) {
	const deduped = new Map<string, AttentionItem>()
	for (const account of accounts) {
		const candidates: AttentionItem[] = []
		if (account.deadLetterActions > 0) candidates.push(item(account, "CRITICAL", "DEAD_LETTER_ACTIONS", "/history", account.signalObservedAt.deadLetter, account.deadLetterActions))
		if (account.failedActions > 0) candidates.push(item(account, "CRITICAL", "FAILED_ACTIONS", "/history", account.signalObservedAt.failed, account.failedActions))
		if (account.openAlerts > 0) candidates.push(item(account, "HIGH", "OPEN_ALERTS", "/history", account.signalObservedAt.alert, account.openAlerts))
		if (account.state === "STALE") candidates.push(item(account, "HIGH", "STALE_DATA", "/history", account.signalObservedAt.freshness))
		if (account.state === "NO_DATA") candidates.push(item(account, "MEDIUM", "NO_PERFORMANCE_DATA", "/history", account.signalObservedAt.freshness))
		if (account.acos != null && account.targetAcos != null && account.acos > account.targetAcos) candidates.push(item(account, "HIGH", "ACOS_ABOVE_TARGET", "/campaigns", account.dataThrough, null, account.acos, account.targetAcos))
		if (account.pendingApprovals > 0) candidates.push(item(account, "MEDIUM", "PENDING_APPROVALS", "/approvals", account.signalObservedAt.approval, account.pendingApprovals))
		for (const candidate of candidates) deduped.set(`${candidate.tenantId}:${candidate.reason}`, candidate)
	}
	const items = [...deduped.values()].sort((left, right) => priority[left.severity] - priority[right.severity] || left.tenantName.localeCompare(right.tenantName) || left.reason.localeCompare(right.reason))
	return {
		items,
		counts: {
			total: items.length,
			critical: items.filter(value => value.severity === "CRITICAL").length,
			high: items.filter(value => value.severity === "HIGH").length,
			medium: items.filter(value => value.severity === "MEDIUM").length,
		},
	}
}
