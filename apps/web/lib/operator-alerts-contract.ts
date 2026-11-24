export const ALERT_SEVERITIES = ["critical", "warning", "info"] as const
export type AlertSeverity = typeof ALERT_SEVERITIES[number]

const targets = {
	amazon: ["/settings/amazon", "Open Amazon connections"],
	history: ["/history#pipeline-runs", "Review pipeline history"],
	decisions: ["/approvals", "Review pending decisions"],
	automation: ["/settings/automation-control", "Review automation controls"],
	economics: ["/economics", "Review SKU economics"],
	inventory: ["/inventory", "Open inventory"],
} as const
const guidance = {
	auth_expiring: ["Amazon authorization expiring", "Ask an authorized administrator to review and renew the affected connection before the next run.", "amazon"],
	auth_expired: ["Amazon authorization unavailable", "Have an authorized administrator check the connection. Resume provider-dependent work only after authorization and data freshness are verified.", "amazon"],
	pipeline_failed: ["Data pipeline failed", "Review the latest run and check the connection or upstream availability before asking an operator to retry.", "history"],
	data_stale: ["Data is stale", "Confirm the most recent successful load before making decisions that depend on this data.", "history"],
	blast_radius_halt: ["Automation safety limit reached", "Review the automation controls and current exposure. Do not bypass the safety limit.", "automation"],
	budget_guard: ["Budget safeguard triggered", "Review the proposal and available budget before taking any action. The inbox does not change budgets.", "decisions"],
	action_failed: ["An action did not complete", "Check the action history and provider state before deciding whether a new guarded action is needed.", "history"],
	economics_incomplete: ["Product cost evidence incomplete", "Review missing costs before using contribution margin or break-even targets.", "economics"],
	low_inventory: ["Low inventory", "Check current stock and confirmed inbound units before planning replenishment.", "inventory"],
	projected_stockout: ["Potential stockout", "Review the forecast, supplier lead time, and confirmed inbound stock.", "inventory"],
	reorder_due: ["Reorder review due", "Review coverage and planned inbound inventory before placing a purchase order.", "inventory"],
	inbound_delayed: ["Inbound inventory delayed", "Confirm the expected receipt date and reassess stock coverage.", "inventory"],
	excess_stock: ["Potential excess inventory", "Review stock coverage and demand before increasing or discounting inventory.", "inventory"],
	unusual_demand: ["Unusual inventory demand", "Check recent demand and data freshness before changing the forecast.", "inventory"],
} as const satisfies Record<string, readonly [string, string, keyof typeof targets]>

export const OPERATOR_ALERT_KINDS = Object.keys(guidance)
export type AlertFilters = { severity: AlertSeverity | null; limit: number }

export function operatorAlertFilters(params: URLSearchParams): AlertFilters | null {
	const severity = params.get("severity")
	const limit = params.get("limit") ?? "25"
	if (params.getAll("severity").length > 1 || params.getAll("limit").length > 1) return null
	if (severity !== null && !ALERT_SEVERITIES.includes(severity as AlertSeverity)) return null
	if (!/^[1-9][0-9]?$/.test(limit) || Number(limit) > 50) return null
	return { severity: severity as AlertSeverity | null, limit: Number(limit) }
}

export type OperatorAlertRow = {
	id: string
	kind: string
	severity: AlertSeverity
	occurred_at: Date
	source: string | null
}

const sources: Readonly<Record<string, string>> = {
	scheduler: "Scheduler", action_worker: "Action worker", inventory_engine: "Inventory engine", internal: "Internal event",
}

export function presentOperatorAlert(row: OperatorAlertRow) {
	if (!Object.hasOwn(guidance, row.kind)) return null
	const [title, nextStep, target] = guidance[row.kind as keyof typeof guidance]
	const [href, label] = row.kind === "action_failed"
		? ["/history", "Review action history"] as const : targets[target]
	const source = row.source === null ? "Legacy alert"
		: Object.hasOwn(sources, row.source) ? sources[row.source] : "Internal event"
	return {
		id: row.id, kind: row.kind, severity: row.severity, occurredAt: row.occurred_at.toISOString(),
		title, source, nextStep, recovery: { href, label },
	}
}
