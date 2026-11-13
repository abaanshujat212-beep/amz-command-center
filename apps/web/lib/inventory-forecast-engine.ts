/** Pure, deterministic port of services/rules/inventory_forecast.py. No I/O or clock reads. */
export const MAX_INVENTORY_FORECAST_DAYS = 3660
const DAY_MS = 86400000
const MIN_DAY = Date.parse("0001-01-01T00:00:00Z") / DAY_MS
const MAX_DAY = Date.parse("9999-12-31T00:00:00Z") / DAY_MS

export type InventoryDailyDemand = { day: string; units: number }
export type InventoryExpectedReceipt = { arrivalDay: string; quantity: number; status?: string }
export type InventoryForecastInput = {
	sku: string; asOf: string; demand: readonly InventoryDailyDemand[];
	position: { availableNow: number | null; reserved?: number | null; inbound?: number | null; expectedLater?: number | null };
	source: string; observedAt: string; leadTimeDays: number | null; leadTimeSamples: number;
	seasonalIndices: Readonly<Record<number, number>>;
	leadTimeObservations?: readonly number[]; receipts?: readonly InventoryExpectedReceipt[];
	staleAfterDays?: number; minimumHistoryDays?: number; partialSource?: boolean;
}
export type InventoryVelocityWindow = {
	windowDays: number; startDay: string | null; endDay: string | null;
	observedDays: number; missingDays: number; coverage: number;
	status: "complete" | "partial" | "no_data";
	unitsObserved: number | null; averageDailyUnitsObserved: number | null;
}
export type InventoryForecastAssumptions = {
	source: string | null; observedAt: string | null;
	historyDays?: number; velocityWindows?: Record<"7d" | "14d" | "30d", InventoryVelocityWindow> | null;
	forecastAverageMethod?: "all_supplied_daily_observations";
	leadTimeDays?: number; leadTimeSamples?: number;
	leadTimeMethod?: "p90_observed" | "provided_summary";
	seasonalityMethod?: "daily_index_ratio"; receiptsAffectFutureOnly?: true;
	reserved?: number | null; inbound?: number | null; expectedLater?: number | null; safetyStockDays?: number;
}
export type InventoryForecast = {
	sku: string; status: "blocked" | "reduced_confidence" | "ready";
	confidence: number; blockers: string[]; assumptions: InventoryForecastAssumptions;
	availableNow: number | null; averageDailyDemand: number | null; daysOfSupplyNow: number | null;
	projectedStockoutDay: string | null; stockoutBeforeReceipt: boolean | null;
	projectedAvailableAtLeadTime: number | null; projectedExcessAtLeadTime: number | null;
	reorderQuantity: number | null; reorderDueDay: string | null;
	forecast: { day: string; demand: number; projectedAvailable: number }[];
}
function record(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value) }
function dayNumber(value: unknown): number | null {
	if (typeof value !== "string" || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value)) return null
	const ms = Date.parse(`${value}T00:00:00Z`)
	return Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 10) === value ? ms / DAY_MS : null
}
function dayString(value: number): string { return new Date(value * DAY_MS).toISOString().slice(0, 10) }
function dayOfYear(value: number): number {
	return value - Date.parse(`${dayString(value).slice(0, 4)}-01-01T00:00:00Z`) / DAY_MS + 1
}
function nonnegative(value: unknown): number | null {
	if (typeof value !== "number" && (typeof value !== "string" || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim()))) return null
	const number = Number(value)
	return Number.isFinite(number) && number >= 0 ? number : null
}
function integer(value: unknown, minimum: number): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum }

/** Round the exact binary float to four decimals, including Python's ties-to-even rule. */
function round4(value: number): number {
	if (!Number.isFinite(value) || value === 0) return value
	const buffer = new ArrayBuffer(8), view = new DataView(buffer)
	view.setFloat64(0, Math.abs(value))
	const bits = view.getBigUint64(0), exponent = Number((bits >> 52n) & 2047n)
	let numerator = ((bits & ((1n << 52n) - 1n)) + (exponent ? 1n << 52n : 0n)) * 10000n
	const shift = (exponent ? exponent - 1023 : -1022) - 52
	let denominator = 1n
	if (shift >= 0) numerator <<= BigInt(shift)
	else denominator <<= BigInt(-shift)
	let quotient = numerator / denominator
	const remainder = numerator % denominator
	if (remainder * 2n > denominator || (remainder * 2n === denominator && quotient % 2n !== 0n)) quotient += 1n
	return Math.sign(value) * Number(`${quotient}e-4`)
}
function velocityWindows(asOf: number, history: { day: number; units: number }[]): Record<"7d" | "14d" | "30d", InventoryVelocityWindow> | null {
	const windows = {} as Record<"7d" | "14d" | "30d", InventoryVelocityWindow>
	for (const days of [7, 14, 30] as const) {
		const start = asOf - days, end = asOf - 1
		const values = history.filter(item => item.day >= start && item.day <= end).map(item => item.units)
		const total = values.length ? values.reduce((sum, value) => sum + value, 0) : null
		if (total !== null && !Number.isFinite(total)) return null
		windows[`${days}d`] = {
			windowDays: days, startDay: start >= MIN_DAY ? dayString(start) : null, endDay: end >= MIN_DAY ? dayString(end) : null,
			observedDays: values.length, missingDays: days - values.length, coverage: round4(values.length / days),
			status: values.length === days ? "complete" : values.length ? "partial" : "no_data",
			unitsObserved: total, averageDailyUnitsObserved: total === null ? null : round4(total / values.length),
		}
	}
	return windows
}

/**
 * Mean-of-supplied-history demand, seasonal index ratios and P90 observed lead time.
 * Matches the Python engine's readout semantics: stale/partial stock reduces confidence;
 * the caller owns sales-source freshness and authorization. Expected receipts affect future stock only.
 */
export function forecastInventory(input: InventoryForecastInput): InventoryForecast {
	const raw: Record<string, unknown> = record(input) ? input : {}
	let windows: InventoryForecastAssumptions["velocityWindows"] = null
	const empty = (blockers: string[]): InventoryForecast => ({
		sku: typeof raw.sku === "string" ? raw.sku : "", status: "blocked", confidence: 0, blockers,
		assumptions: { source: typeof raw.source === "string" ? raw.source : null,
			observedAt: dayNumber(raw.observedAt) === null ? null : raw.observedAt as string,
			...(windows === null ? {} : { velocityWindows: windows }) },
		availableNow: null, averageDailyDemand: null, daysOfSupplyNow: null, projectedStockoutDay: null,
		stockoutBeforeReceipt: null, projectedAvailableAtLeadTime: null, projectedExcessAtLeadTime: null,
		reorderQuantity: null, reorderDueDay: null, forecast: [],
	})
	if (typeof raw.sku !== "string" || !raw.sku.trim() || typeof raw.source !== "string" || !raw.source.trim()) return empty(["missing_identity_or_source"])
	const blockers: string[] = []
	const staleAfter = raw.staleAfterDays === undefined ? 3 : raw.staleAfterDays
	const minimumHistory = raw.minimumHistoryDays === undefined ? 14 : raw.minimumHistoryDays
	if (!integer(staleAfter, 0)) blockers.push("invalid_freshness_policy")
	if (!integer(minimumHistory, 1)) blockers.push("invalid_history_policy")
	if (!integer(raw.leadTimeSamples, 1)) blockers.push("lead_time_distribution_missing")
	const asOf = dayNumber(raw.asOf), observedAt = dayNumber(raw.observedAt)
	if (asOf === null || observedAt === null) blockers.push("invalid_input_dates")
	if (blockers.length || asOf === null || observedAt === null || !integer(staleAfter, 0) || !integer(minimumHistory, 1) || !integer(raw.leadTimeSamples, 1)) return empty(blockers)
	if (!Array.isArray(raw.demand) || raw.demand.some(item => !record(item) || dayNumber(item.day) === null)) return empty(["invalid_demand_dates"])
	if (!record(raw.position)) return empty(["available_now_unknown_or_invalid"])
	const available = nonnegative(raw.position.availableNow)
	if (available === null) blockers.push("available_now_unknown_or_invalid")
	if (observedAt > asOf) blockers.push("source_timestamp_in_future")
	const age = asOf - observedAt
	if (age > staleAfter) blockers.push("inventory_source_stale")
	if (raw.partialSource) blockers.push("inventory_source_partial")
	const history = raw.demand.map(item => ({ day: dayNumber(item.day)!, units: nonnegative(item.units) })).sort((a, b) => a.day - b.day)
	if (new Set(history.map(item => item.day)).size !== history.length) blockers.push("duplicate_demand_dates")
	if (history.some(item => item.day > asOf)) blockers.push("demand_timestamp_in_future")
	if (history.some(item => item.units === null)) blockers.push("invalid_demand_history")
	const values = history.flatMap(item => item.units === null ? [] : [item.units])
	if (!["duplicate_demand_dates", "demand_timestamp_in_future", "invalid_demand_history"].some(reason => blockers.includes(reason))) {
		windows = velocityWindows(asOf, history as { day: number; units: number }[])
	}
	if (values.length < minimumHistory) blockers.push("sparse_demand_history")
	let lead = nonnegative(raw.leadTimeDays)
	const observations = raw.leadTimeObservations === undefined ? [] : raw.leadTimeObservations
	let leads: number[] = []
	if (!Array.isArray(observations) || observations.some(item => nonnegative(item) === null)) blockers.push("invalid_lead_time_distribution")
	else leads = observations.map(item => nonnegative(item)!).sort((a, b) => a - b)
	if (leads.length) lead = leads[Math.ceil(0.9 * leads.length) - 1]
	if (lead === null) blockers.push("lead_time_unknown")
	if (lead !== null && lead > MAX_INVENTORY_FORECAST_DAYS) blockers.push("forecast_horizon_exceeded")
	const indices = new Map<number, number>()
	if (!record(raw.seasonalIndices)) blockers.push("invalid_seasonality_profile")
	else for (const [key, value] of Object.entries(raw.seasonalIndices)) {
		const index = nonnegative(value), day = Number(key)
		if (String(day) !== key || !integer(day, 1) || day > 366 || index === null) { blockers.push("invalid_seasonality_profile"); break }
		indices.set(day, index)
	}
	if (blockers.some(reason => reason !== "inventory_source_stale" && reason !== "inventory_source_partial") || available === null || lead === null) return empty(blockers)
	const leadDays = Math.ceil(lead), horizon = Math.max(leadDays, 1)
	if (asOf + horizon > MAX_DAY) return empty([...blockers, "forecast_date_range_exceeded"])
	const average = values.reduce((sum, value) => sum + value, 0) / values.length
	if (!Number.isFinite(average)) return empty([...blockers, "nonfinite_forecast_calculation"])
	const baseIndex = indices.get(dayOfYear(asOf)) ?? 0
	const receipts = new Map<number, number>()
	const rawReceipts = raw.receipts === undefined ? [] : raw.receipts
	if (!Array.isArray(rawReceipts)) return empty([...blockers, "invalid_expected_receipt"])
	for (const item of rawReceipts) {
		if (!record(item)) return empty([...blockers, "invalid_expected_receipt"])
		if ((item.status === undefined ? "expected" : item.status) !== "expected") continue
		const arrival = dayNumber(item.arrivalDay), quantity = nonnegative(item.quantity)
		if (arrival === null || arrival < asOf || quantity === null) return empty([...blockers, "invalid_expected_receipt"])
		receipts.set(arrival, (receipts.get(arrival) ?? 0) + quantity)
	}
	let projected = available, stockoutDay: string | null = null, stockoutBeforeReceipt: boolean | null = null
	const points: InventoryForecast["forecast"] = []
	for (let offset = 1; offset <= horizon; offset += 1) {
		const day = asOf + offset, index = indices.get(dayOfYear(day)) ?? baseIndex
		const dailyDemand = average * (baseIndex > 0 ? index / baseIndex : 1)
		projected += receipts.get(day) ?? 0
		projected -= dailyDemand
		if (!Number.isFinite(dailyDemand) || !Number.isFinite(projected)) return empty([...blockers, "nonfinite_forecast_calculation"])
		if (projected <= 0 && dailyDemand > 0 && stockoutDay === null) {
			stockoutDay = dayString(day)
			stockoutBeforeReceipt = ![...receipts.keys()].some(arrival => arrival <= day)
		}
		points.push({ day: dayString(day), demand: dailyDemand, projectedAvailable: Math.max(0, projected) })
	}
	const daysSupply = average > 0 ? available / average : null
	if (daysSupply !== null && !Number.isFinite(daysSupply)) return empty([...blockers, "nonfinite_forecast_calculation"])
	const leadDemand = points.slice(0, leadDays).reduce((sum, point) => sum + point.demand, 0)
	const receiptUnits = [...receipts.entries()].filter(([day]) => day > asOf && day <= asOf + leadDays).reduce((sum, [, quantity]) => sum + quantity, 0)
	if (!Number.isFinite(leadDemand) || !Number.isFinite(receiptUnits)) return empty([...blockers, "nonfinite_forecast_calculation"])
	const availableAtLead = Math.max(0, available + receiptUnits - leadDemand), safetyStock = average * lead
	if (!Number.isFinite(availableAtLead) || !Number.isFinite(safetyStock)) return empty([...blockers, "nonfinite_forecast_calculation"])
	const reorderQuantity = Math.max(0, safetyStock - availableAtLead)
	const dueDay = asOf + Math.max(0, Math.floor((daysSupply ?? 0) - lead))
	if (dueDay > MAX_DAY) return empty([...blockers, "forecast_date_range_exceeded"])
	let confidence = Math.min(1, values.length / (minimumHistory * 2))
	confidence *= Math.min(1, raw.leadTimeSamples / 10)
	confidence *= Math.max(0, 1 - Math.max(age, 0) / Math.max(staleAfter + 1, 1))
	if (raw.partialSource) confidence *= 0.5
	if (baseIndex === 0 && indices.size) blockers.push("seasonality_base_missing")
	return {
		sku: raw.sku, status: blockers.length ? "reduced_confidence" : "ready", confidence: round4(confidence), blockers,
		assumptions: { source: raw.source, observedAt: raw.observedAt as string, historyDays: values.length, velocityWindows: windows,
			forecastAverageMethod: "all_supplied_daily_observations", leadTimeDays: lead, leadTimeSamples: raw.leadTimeSamples,
			leadTimeMethod: leads.length ? "p90_observed" : "provided_summary", seasonalityMethod: "daily_index_ratio", receiptsAffectFutureOnly: true,
			reserved: input.position.reserved === undefined ? 0 : input.position.reserved,
			inbound: input.position.inbound === undefined ? 0 : input.position.inbound,
			expectedLater: input.position.expectedLater === undefined ? 0 : input.position.expectedLater, safetyStockDays: lead },
		availableNow: available, averageDailyDemand: round4(average), daysOfSupplyNow: daysSupply === null ? null : round4(daysSupply),
		projectedStockoutDay: stockoutDay, stockoutBeforeReceipt, projectedAvailableAtLeadTime: round4(availableAtLead),
		projectedExcessAtLeadTime: round4(Math.max(0, availableAtLead - safetyStock)), reorderQuantity: round4(reorderQuantity), reorderDueDay: dayString(dueDay), forecast: points,
	}
}
