/** Local location types that can be created from a manual stock observation. */
export const MANUAL_INVENTORY_LOCATION_TYPES = [
	{ value: "own_warehouse", label: "Own warehouse" },
	{ value: "third_party_logistics", label: "Third-party logistics (3PL)" },
	{ value: "prep_center", label: "Prep center" },
	{ value: "supplier", label: "Supplier" },
	{ value: "in_transit", label: "In transit" },
	{ value: "other", label: "Other local location" },
] as const

export type ManualInventoryLocationType = typeof MANUAL_INVENTORY_LOCATION_TYPES[number]["value"]
export function isManualInventoryLocationType(value: unknown): value is ManualInventoryLocationType {
	return MANUAL_INVENTORY_LOCATION_TYPES.some(option => option.value === value)
}
