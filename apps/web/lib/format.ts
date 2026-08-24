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

/**
 * Timestamps for decisions and applies: date plus time of day.
 *
 * reportDate() is for report dates, which have no time. A decision does: "who
 * approved this and when" cannot be answered to the nearest day when several
 * changes to the same entity can happen in one afternoon.
 */
export function stamp(value: string | Date | null | undefined): string {
	if (value === null || value === undefined) return "—"
	const d = typeof value === "string" ? new Date(value) : value
	if (Number.isNaN(d.getTime())) return "—"
	return new Intl.DateTimeFormat(LOCALE, {
		day: "2-digit",
		month: "short",
		hour: "2-digit",
		minute: "2-digit",
		hour12: false,
		timeZone: REPORTING_TZ,
	}).format(d)
}

/** Compact integers for impression and click counts. */
export function count(value: number | null | undefined): string {
	if (value === null || value === undefined) return "—"
	return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 }).format(
		value,
	)
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

/**
 * Compare a rate to the account benchmark. Used on the keyword drill-down.
 *
 * "Low CTR" has no absolute value: 0.3% is normal for broad discovery and
 * alarming for a branded exact. Unknown benchmark means no verdict, not a
 * neutral one.
 */
export function benchmarkTone(
	value: number | null,
	benchmark: number | null,
): "good" | "warn" | "bad" | "unknown" {
	if (value === null || benchmark === null || benchmark === 0) return "unknown"
	const ratio = value / benchmark
	if (ratio >= 1.1) return "good"
	if (ratio >= 0.6) return "warn"
	return "bad"
}
