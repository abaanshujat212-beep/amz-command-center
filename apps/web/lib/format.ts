/** Presentation helpers. UK marketplace: GBP and Europe/London everywhere. */

const CURRENCY = process.env.NEXT_PUBLIC_CURRENCY ?? "GBP"
const LOCALE = "en-GB"
export const REPORTING_TZ = "Europe/London"

export function money(value: number | null | undefined): string {
	if (value === null || value === undefined) return "—"
	return new Intl.NumberFormat(LOCALE, {
		style: "currency",
		currency: CURRENCY,
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
	}).format(value)
}

/**
 * Percentages: null means "unknown" (no clicks, no impressions) and renders as
 * an em dash. Never show 0% for missing data — that reads as good performance.
 */
export function percent(value: number | null | undefined, digits = 1): string {
	if (value === null || value === undefined) return "—"
	return new Intl.NumberFormat(LOCALE, {
		style: "percent",
		minimumFractionDigits: digits,
		maximumFractionDigits: digits,
	}).format(value)
}

export function reportDate(value: string | Date): string {
	const d = typeof value === "string" ? new Date(value) : value
	return new Intl.DateTimeFormat(LOCALE, {
		day: "2-digit",
		month: "short",
		year: "numeric",
		timeZone: REPORTING_TZ,
	}).format(d)
}

/** ACOS colouring is relative to break-even, not to a vanity target. */
export function acosTone(
	acos: number | null,
	breakEvenAcos: number | null,
): "good" | "warn" | "bad" | "unknown" {
	if (acos === null || breakEvenAcos === null) return "unknown"
	if (acos <= breakEvenAcos * 0.7) return "good"
	if (acos <= breakEvenAcos) return "warn"
	return "bad"
}
