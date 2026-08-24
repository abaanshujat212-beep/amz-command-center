/**
 * Reporting windows the UI is allowed to ask for.
 *
 * This is a closed list, not a free number, and that is a data-honesty decision
 * rather than a UI simplification. Ads API v3 reports reach back roughly 95 days
 * (Sponsored Display and SB v2: 60). A ?days=180 request cannot be answered, and
 * the failure mode is the dangerous kind: the query succeeds and returns however
 * much history happens to exist, presented as a 180-day number.
 *
 * 90 is therefore the largest option -- comfortably inside the wall, so a full
 * window is really a full window.
 */

export const ALLOWED_WINDOWS = [7, 14, 30, 60, 90] as const

export type Window = (typeof ALLOWED_WINDOWS)[number]

export const DEFAULT_WINDOW: Window = 30

/** Largest window we offer. Kept below the ~95 day Ads reporting limit. */
export const MAX_WINDOW: Window = 90

function isWindow(n: number): n is Window {
	return (ALLOWED_WINDOWS as readonly number[]).includes(n)
}

/**
 * Parse ?days= from a search param.
 *
 * Anything unrecognised becomes the default. A hand-edited or stale URL should
 * render the default view, not an error page -- and never a window the data
 * cannot support.
 */
export function parseDays(raw: string | string[] | undefined): Window {
	const first = Array.isArray(raw) ? raw[0] : raw
	if (!first) return DEFAULT_WINDOW
	const n = Number.parseInt(first, 10)
	if (!Number.isFinite(n) || !isWindow(n)) return DEFAULT_WINDOW
	return n
}

/** Preserve every other query param when switching window. */
export function windowHref(
	pathname: string,
	days: Window,
	extra: Record<string, string | undefined> = {},
): string {
	const params = new URLSearchParams()
	for (const [k, v] of Object.entries(extra)) {
		if (v !== undefined && v !== "") params.set(k, v)
	}
	params.set("days", String(days))
	return `${pathname}?${params.toString()}`
}
