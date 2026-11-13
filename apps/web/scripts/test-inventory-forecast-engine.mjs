import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { spawnSync } from "node:child_process"
import test from "node:test"
import vm from "node:vm"
import ts from "typescript"

const module = { exports: {} }
class NoClock extends Date { static now() { throw Error("The pure engine must not read the wall clock") } }
vm.runInNewContext(ts.transpile(readFileSync(new URL("../lib/inventory-forecast-engine.ts", import.meta.url), "utf8"), { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }), {
	exports: module.exports, module, Date: NoClock,
	require() { throw Error("The pure engine must not import I/O") },
})
const { forecastInventory } = module.exports
const asOf = "2026-01-01", day = offset => new Date(Date.parse(`${asOf}T00:00:00Z`) + offset * 86400000).toISOString().slice(0, 10)
function fixture(changes = {}) {
	return { sku: "SKU", asOf, observedAt: asOf, source: "csv_import", demand: Array.from({ length: 30 }, (_, i) => ({ day: day(-i - 1), units: 5 })),
		position: { availableNow: 100 }, leadTimeDays: 4, leadTimeSamples: 10, seasonalIndices: {}, ...changes }
}
const plain = value => JSON.parse(JSON.stringify(value))
function blocked(input, reason) {
	const result = forecastInventory(input)
	assert.equal(result.status, "blocked"); assert.equal(result.confidence, 0)
	assert.ok(result.blockers.includes(reason), result.blockers.join(","))
	assert.equal(result.reorderQuantity, null); assert.equal(result.projectedStockoutDay, null)
	assert.deepEqual(plain(result.forecast), [])
}
test("current availability stays separate from reserved, inbound and unknown expected stock", () => {
	const result = forecastInventory(fixture({ position: { availableNow: 10, reserved: 3, inbound: 100, expectedLater: null } }))
	assert.equal(result.status, "ready"); assert.equal(result.availableNow, 10); assert.equal(result.daysOfSupplyNow, 2)
	assert.equal(result.assumptions.inbound, 100); assert.equal(result.assumptions.expectedLater, null)
})
test("seasonality and dated receipts change only future stock", () => {
	const result = forecastInventory(fixture({ position: { availableNow: 20 }, leadTimeDays: 2, seasonalIndices: { 1: 5, 2: 10 }, receipts: [{ arrivalDay: day(1), quantity: 10 }] }))
	assert.equal(result.availableNow, 20); assert.equal(result.forecast[0].demand, 10)
	assert.equal(result.forecast[0].projectedAvailable, 20); assert.equal(result.projectedAvailableAtLeadTime, 15)
})
for (const arrival of [0, 5, 30]) test(`receipt outside lead horizon (${arrival}) does not inflate lead-time stock`, () => {
	const result = forecastInventory(fixture({ position: { availableNow: 10 }, receipts: [{ arrivalDay: day(arrival), quantity: 100 }] }))
	assert.equal(result.projectedAvailableAtLeadTime, 0); assert.equal(result.reorderQuantity, 20)
})
test("receipt on the lead boundary counts, while canceled receipts do not", () => {
	const result = forecastInventory(fixture({ position: { availableNow: 10 }, receipts: [{ arrivalDay: day(4), quantity: 100 }, { arrivalDay: day(2), quantity: 999, status: "canceled" }] }))
	assert.equal(result.projectedAvailableAtLeadTime, 90); assert.equal(result.reorderQuantity, 0)
})
test("zero lead time preserves current stock rather than consuming visualization demand", () => {
	const result = forecastInventory(fixture({ position: { availableNow: 10 }, leadTimeDays: 0, receipts: [{ arrivalDay: day(1), quantity: 100 }] }))
	assert.equal(result.projectedAvailableAtLeadTime, 10); assert.equal(result.projectedExcessAtLeadTime, 10)
})
test("P90 lead-time observations and input sample confidence match the Python contract", () => {
	const result = forecastInventory(fixture({ leadTimeObservations: [2, 3, 4, 12] }))
	assert.equal(result.assumptions.leadTimeDays, 12); assert.equal(result.assumptions.leadTimeMethod, "p90_observed")
	assert.equal(result.forecast.at(-1).day, day(12)); assert.equal(result.confidence, 1)
})
test("sparse input blocks replenishment but retains completed-day velocity evidence", () => {
	const input = fixture({ demand: [{ day: day(-1), units: 6 }, { day: day(-3), units: 0 }, { day: day(-7), units: 3 }] })
	blocked(input, "sparse_demand_history")
	const window = forecastInventory(input).assumptions.velocityWindows["7d"]
	assert.equal(window.observedDays, 3); assert.equal(window.missingDays, 4)
	assert.equal(window.unitsObserved, 9); assert.equal(window.averageDailyUnitsObserved, 3)
})
test("current day is excluded from windows, explicit zero remains observed, absence remains unknown", () => {
	const result = forecastInventory(fixture({ demand: [{ day: asOf, units: 100 }, { day: day(-7), units: 0 }, { day: day(-31), units: 999 }] }))
	assert.equal(result.assumptions.velocityWindows["7d"].unitsObserved, 0)
	assert.equal(result.assumptions.velocityWindows["7d"].observedDays, 1)
	const empty = forecastInventory(fixture({ demand: [] })).assumptions.velocityWindows["7d"]
	assert.equal(empty.unitsObserved, null); assert.equal(empty.averageDailyUnitsObserved, null)
})
test("stale and partial source readouts explicitly reduce confidence", () => {
	const result = forecastInventory(fixture({ observedAt: day(-9), partialSource: true }))
	assert.equal(result.status, "reduced_confidence"); assert.equal(result.confidence, 0)
	assert.ok(result.blockers.includes("inventory_source_stale")); assert.ok(result.blockers.includes("inventory_source_partial"))
})
for (const [key, value, reason] of [
	["staleAfterDays", "3", "invalid_freshness_policy"], ["minimumHistoryDays", 0, "invalid_history_policy"],
	["leadTimeSamples", false, "lead_time_distribution_missing"], ["asOf", "2026-02-30", "invalid_input_dates"],
	["observedAt", null, "invalid_input_dates"], ["observedAt", day(1), "source_timestamp_in_future"],
	["leadTimeObservations", [2, NaN], "invalid_lead_time_distribution"], ["leadTimeDays", 3661, "forecast_horizon_exceeded"],
	["seasonalIndices", { 1: Infinity }, "invalid_seasonality_profile"],
]) test(`invalid ${key} fails closed`, () => blocked(fixture({ [key]: value }), reason))
for (const amount of [null, -1, NaN, Infinity, true]) test(`invalid current stock ${amount} stays unknown`, () => blocked(fixture({ position: { availableNow: amount } }), "available_now_unknown_or_invalid"))
test("duplicate, future and malformed demand cannot produce actionable estimates", () => {
	const input = fixture()
	blocked({ ...input, demand: [...input.demand, input.demand[0]] }, "duplicate_demand_dates")
	blocked({ ...input, demand: [...input.demand, { day: day(1), units: 100 }] }, "demand_timestamp_in_future")
	blocked({ ...input, demand: [{ day: null, units: 5 }] }, "invalid_demand_dates")
	blocked({ ...input, demand: input.demand.map(row => ({ ...row, units: NaN })) }, "invalid_demand_history")
})
test("invalid receipt calendars and nonfinite derived values fail closed", () => {
	blocked(fixture({ receipts: [{ arrivalDay: "bad", quantity: 10 }] }), "invalid_expected_receipt")
	blocked(fixture({ demand: fixture().demand.map(row => ({ ...row, units: 1e308 })) }), "nonfinite_forecast_calculation")
	blocked(fixture({ position: { availableNow: 1e308 }, demand: fixture().demand.map(row => ({ ...row, units: 1e-300 })) }), "nonfinite_forecast_calculation")
	blocked(fixture({ position: { availableNow: 1e9 } }), "forecast_date_range_exceeded")
	blocked(fixture({ asOf: "9999-12-30", observedAt: "9999-12-30" }), "forecast_date_range_exceeded")
})
test("binary halfway rounding preserves Python's even-decimal result", () => {
	assert.equal(forecastInventory(fixture({ demand: fixture().demand.map(row => ({ ...row, units: 0.03125 })) })).averageDailyDemand, 0.0312)
	assert.equal(forecastInventory(fixture({ demand: fixture().demand.map(row => ({ ...row, units: 0.09375 })) })).averageDailyDemand, 0.0938)
})
test("same input produces identical JSON-safe output without mutations, clocks or imports", () => {
	const input = fixture(), before = JSON.stringify(input)
	assert.deepEqual(plain(forecastInventory(input)), plain(forecastInventory(input)))
	assert.equal(JSON.stringify(input), before)
})

// Optional local cross-language oracle. Regular Node tests do not require Python.
if (process.env.INVENTORY_FORECAST_PYTHON) test("Python/TypeScript parity corpus", () => {
	const corpus = [fixture(), fixture({ position: { availableNow: 5 } }), fixture({ position: { availableNow: 500 } }),
		fixture({ seasonalIndices: { 1: 5, 2: 10 }, receipts: [{ arrivalDay: day(1), quantity: 10 }] }),
		fixture({ leadTimeObservations: [2, 3, 4, 12] }), fixture({ leadTimeDays: 0 }),
		fixture({ receipts: [{ arrivalDay: day(4), quantity: 100 }] }), fixture({ receipts: [{ arrivalDay: day(5), quantity: 100 }] }),
		fixture({ observedAt: day(-9), partialSource: true }), fixture({ demand: [] }),
		fixture({ seasonalIndices: { 2: 2 } }), fixture({ demand: fixture().demand.map(row => ({ ...row, units: 0 })) }),
		fixture({ demand: fixture().demand.map(row => ({ ...row, units: 0.03125 })) }),
	]
	const python = String.raw`
import json,sys,re
from datetime import date
from services.rules.inventory_forecast import DailyDemand,ExpectedReceipt,InventoryPosition,InventoryForecastInput,forecast_inventory

def snake(key): return re.sub(r'[A-Z]', lambda m:'_'+m.group(0).lower(),key)
def camel(key): return re.sub(r'_([a-z])',lambda m:m.group(1).upper(),key)
def convert(value):
 if isinstance(value,dict): return {camel(k):convert(v) for k,v in value.items()}
 if isinstance(value,list): return [convert(v) for v in value]
 return value
results=[]
for raw in json.load(sys.stdin):
 data={snake(k):v for k,v in raw.items()}
 data['as_of']=date.fromisoformat(data['as_of']);data['observed_at']=date.fromisoformat(data['observed_at'])
 data['demand']=[DailyDemand(date.fromisoformat(r['day']),r['units']) for r in data['demand']]
 data['position']=InventoryPosition(**{snake(k):v for k,v in data['position'].items()})
 data['seasonal_indices']={int(k):v for k,v in data['seasonal_indices'].items()}
 data['receipts']=[ExpectedReceipt(date.fromisoformat(r['arrivalDay']),r['quantity'],r.get('status','expected')) for r in data.get('receipts',[])]
 results.append(convert(forecast_inventory(InventoryForecastInput(**data)).as_dict()))
print(json.dumps(results,default=lambda x:x.isoformat()))`
	const result = spawnSync(process.env.INVENTORY_FORECAST_PYTHON, ["-c", python], { cwd: new URL("../../../", import.meta.url), input: JSON.stringify(corpus), encoding: "utf8" })
	assert.equal(result.status, 0, result.stderr)
	const expected = JSON.parse(result.stdout)
	corpus.forEach((input, index) => assert.deepEqual(plain(forecastInventory(input)), expected[index], `parity case ${index}`))
})
