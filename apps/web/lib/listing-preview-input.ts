export function parseListingVersion(raw: unknown): number | null {
	if (typeof raw !== "string" || !/^[1-9][0-9]{0,9}$/.test(raw)) return null
	const version = Number(raw)
	return version <= 2147483647 ? version : null
}
