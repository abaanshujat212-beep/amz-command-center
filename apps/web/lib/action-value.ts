/**
 * Reading the values stored on an action row.
 *
 * The engine writes jsonb, shaped {"value": n} for changes and {"value": null}
 * for diagnostics. Unwrapping returns null for "unknown" rather than a dash, so
 * the caller chooses the wording. A formatting helper that decides what missing
 * data looks like ends up deciding it differently on every screen.
 */

/** Unwrap {"value": x} to a display string. null means genuinely unknown. */
export function shown(v: unknown): string | null {
	if (v === null || v === undefined) return null
	if (typeof v === "object" && "value" in (v as Record<string, unknown>)) {
		const inner = (v as { value: unknown }).value
		if (inner === null || inner === undefined) return null
		return String(inner)
	}
	if (typeof v === "string") return v
	if (typeof v === "number" || typeof v === "boolean") return String(v)
	return JSON.stringify(v)
}

/** Action types whose value is an amount of money, so it renders as currency. */
export const MONEY_ACTIONS = new Set(["set_bid", "set_budget"])

export function isMoneyAction(actionType: string): boolean {
	return MONEY_ACTIONS.has(actionType)
}

/** Numeric value of an action side, or null when it is not a number. */
export function numericValue(v: unknown): number | null {
	const text = shown(v)
	if (text === null) return null
	const n = Number(text)
	return Number.isFinite(n) ? n : null
}
