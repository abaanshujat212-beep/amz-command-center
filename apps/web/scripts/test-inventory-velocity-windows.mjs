import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../lib/inventory.ts", import.meta.url), "utf8")
const module = { exports: {} }
let rows = []
let parameters = []
class Clock extends Date { static now() { return Date.parse("2026-01-01T00:05:00Z") } }
vm.runInNewContext(ts.transpile(source, { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }), {
	exports: module.exports, module, Date: Clock,
	require: name => { assert.equal(name, "@/lib/db"); return { query: async (_client, _sql, params) => { parameters = params; return rows } } },
})
function window(days, changes = {}) {
	return { windowDays: days, startDay: days === 7 ? "2025-12-25" : days === 14 ? "2025-12-18" : "2025-12-02", endDay: "2025-12-31", observedDays: days, missingDays: 0, coverage: 1, status: "complete", unitsObserved: days * 5, averageDailyUnitsObserved: 5, invalidRows: 0, numericRangeExceeded: false, salesFreshness: "current", salesLoadedAt: "2025-12-31T23:00:00Z", latestSalesDate: "2025-12-31", ...changes }
}
function row(changes = {}) {
	return { sku: "SKU", available_qty: 100, observed_at: "2025-12-31T23:00:00Z", freshness_state: "current", average_daily_demand: 5, observed_days: 30, loaded_at: "2025-12-31T23:00:00Z", invalid_demand_rows: 0, numeric_range_exceeded: false, sales_freshness: "current", latest_sales_date: "2025-12-31", velocity_windows: { "7d": window(7), "14d": window(14), "30d": window(30) }, ...changes }
}
async function read(value) {
	rows = [value]
	return (await module.exports.inventoryForecastRead({}, "tenant-test", 72))[0]
}
test("complete valid windows retain prior ready forecast and query tenant", async () => {
	const input = row()
	const result = await read(input)
	assert.equal(result.status, "ready")
	assert.equal(result.averageDailyDemand, 5)
	assert.equal(result.daysOfSupply, 20)
	assert.equal(result.projectedStockoutDay, "2026-01-21")
	assert.equal(result.confidence, 1)
	assert.equal(result.assumptions.velocityWindows, input.velocity_windows)
	assert.equal(parameters[0], "tenant-test")
	assert.equal(parameters[1], 72)
})
test("partial products retain historical observed windows while forecast stays blocked", async () => {
	const input = row({ observed_days: 7 })
	input.velocity_windows["14d"] = window(14, { observedDays: 7, missingDays: 7, coverage: 0.5, status: "partial", unitsObserved: 35 })
	input.velocity_windows["30d"] = window(30, { observedDays: 7, missingDays: 23, coverage: 0.2333, status: "partial", unitsObserved: 35 })
	const result = await read(input)
	assert.equal(result.status, "blocked")
	assert.equal(result.averageDailyDemand, null)
	assert.equal(result.daysOfSupply, null)
	assert.equal(result.projectedStockoutDay, null)
	assert.equal(result.assumptions.velocityWindows["7d"].unitsObserved, 35)
	assert.equal(result.assumptions.velocityWindows["14d"].averageDailyUnitsObserved, 5)
	assert.ok(result.blockers.includes("incomplete_demand_history"))
})
test("unknown no-data values are not converted into observed zero", async () => {
	const windows = Object.fromEntries([7, 14, 30].map(days => [`${days}d`, window(days, { observedDays: 0, missingDays: days, coverage: 0, status: "no_data", unitsObserved: null, averageDailyUnitsObserved: null, salesFreshness: "unknown", salesLoadedAt: null, latestSalesDate: null })]))
	const result = await read(row({ observed_days: 0, average_daily_demand: null, sales_freshness: "unknown", velocity_windows: windows }))
	assert.equal(result.assumptions.velocityWindows["7d"].unitsObserved, null)
	assert.equal(result.status, "blocked")
	assert.equal(result.confidence, 0)
})
test("known zero demand stays zero without an invented stockout date", async () => {
	const result = await read(row({ average_daily_demand: 0, velocity_windows: Object.fromEntries([7, 14, 30].map(days => [`${days}d`, window(days, { unitsObserved: 0, averageDailyUnitsObserved: 0 })])) }))
	assert.equal(result.status, "ready")
	assert.equal(result.averageDailyDemand, 0)
	assert.equal(result.daysOfSupply, null)
	assert.equal(result.projectedStockoutDay, null)
	assert.equal(result.assumptions.velocityWindows["7d"].unitsObserved, 0)
})
test("invalid and unsafe numeric histories never become projections", async () => {
	for (const changes of [{ invalid_demand_rows: 1 }, { numeric_range_exceeded: true }]) {
		const result = await read(row({ ...changes, average_daily_demand: null }))
		assert.equal(result.status, "blocked")
		assert.equal(result.daysOfSupply, null)
		assert.equal(result.projectedStockoutDay, null)
		assert.equal(result.confidence, 0)
	}
})
for (const freshness of ["stale", "unknown"]) test(`${freshness} sales retain windows without creating a forecast`, async () => {
	const input = row({ sales_freshness: freshness })
	input.velocity_windows["7d"].salesFreshness = freshness
	const result = await read(input)
	assert.equal(result.status, "blocked")
	assert.equal(result.daysOfSupply, null)
	assert.equal(result.projectedStockoutDay, null)
	assert.equal(result.assumptions.velocityWindows["7d"].salesFreshness, freshness)
})
for (const freshness of ["stale", "partial", "unknown"]) test(`${freshness} stock cannot produce an actionable date`, async () => {
	const result = await read(row({ freshness_state: freshness }))
	assert.equal(result.status, "blocked")
	assert.equal(result.daysOfSupply, null)
	assert.equal(result.projectedStockoutDay, null)
	assert.equal(result.confidence, 0)
	assert.equal(result.assumptions.velocityWindows["7d"].unitsObserved, 35)
})
for (const [available, average] of [[900000000000, 1 / 30], [3000000, 1]]) test(`unsupported date range fails closed for ${available}/${average}`, async () => {
	const result = await read(row({ available_qty: available, average_daily_demand: average }))
	assert.equal(result.status, "blocked")
	assert.ok(result.blockers.includes("stockout_date_range_exceeded"))
	assert.equal(result.projectedStockoutDay, null)
	assert.equal(result.confidence, 0)
	assert.equal(result.assumptions.velocityWindows["7d"].unitsObserved, 35)
})
