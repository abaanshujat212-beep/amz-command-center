/** Query state for the read-only inventory workspace. */
export type InventoryFilters = { sku?: string; locationCode?: string; page: number; pageSize: number; freshHours: number }
export type InventorySearch = Record<string, string | string[] | undefined>

export function inventoryFilters(search: InventorySearch): InventoryFilters | null {
	const text = (key: string) => typeof search[key] === "string" ? search[key].trim() : search[key] === undefined ? "" : null
	const sku = text("sku")
	const locationCode = text("location")
	const page = text("page")
	const freshHours = text("freshHours")
	if (sku === null || locationCode === null || page === null || freshHours === null || sku.length > 100 || locationCode.length > 100) return null
	if ((page && !/^[1-9]\d*$/.test(page)) || (freshHours && !/^[1-9]\d*$/.test(freshHours))) return null
	const pageNumber = Number(page || 1)
	const hours = Number(freshHours || 72)
	if (!Number.isSafeInteger(pageNumber) || pageNumber > Math.floor(Number.MAX_SAFE_INTEGER / 25) || !Number.isInteger(hours) || hours > 8760) return null
	return { sku: sku || undefined, locationCode: locationCode || undefined, page: pageNumber, pageSize: 25, freshHours: hours }
}

export function inventoryPageHref(filters: InventoryFilters, page: number) {
	const params = new URLSearchParams({ page: String(page), freshHours: String(filters.freshHours) })
	if (filters.sku) params.set("sku", filters.sku)
	if (filters.locationCode) params.set("location", filters.locationCode)
	return `/inventory?${params}`
}
