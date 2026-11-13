import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../lib/inventory-intake.ts", import.meta.url), "utf8")
const locationTypes = { exports: {} }
vm.runInNewContext(ts.transpile(readFileSync(new URL("../lib/inventory-location-types.ts", import.meta.url), "utf8"), { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }), { exports: locationTypes.exports, module: locationTypes })
const module = { exports: {} }
vm.runInNewContext(ts.transpile(source, { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }), {
	exports: module.exports, module, Date, Request, Response, TextDecoder, Uint8Array,
	require: name => { if (name === "@/lib/inventory-location-types") return locationTypes.exports; assert.equal(name, "@/lib/db"); return { query: async (client, sql, params) => (await client.query(sql, params)).rows } },
})
const { InventoryIntakeError, assertManualInventoryRole, parseManualInventoryInput, readInventoryIntakeBody, recordManualInventory, recordCsvInventory } = module.exports
const base = () => ({ locationCode: "warehouse", locationName: "Warehouse", sku: "SKU", sourceReference: "count-1", observedAt: "2026-01-01T12:00:00Z", availableQty: 0 })

for (const role of ["viewer", "analyst", "user"]) test(`${role} cannot record inventory`, () => assert.throws(() => assertManualInventoryRole(role), error => error.status === 403))
for (const role of ["owner", "admin"]) test(`${role} can record inventory`, () => assert.doesNotThrow(() => assertManualInventoryRole(role)))
test("unknown quantity stays null and explicit zero stays zero", () => {
	const parsed = parseManualInventoryInput(base())
	assert.equal(parsed.quantities[0], null)
	assert.equal(parsed.quantities[1], "0")
	assert.equal(parsed.freshness, "current")
})
for (const amount of [-1, Infinity, NaN, true, "5", 1e12, 0.00001]) test(`reject invalid quantity ${String(amount)}`, () => assert.throws(() => parseManualInventoryInput({ ...base(), availableQty: amount }), InventoryIntakeError))
for (const amount of [0.0001, 1.0001, 0.0003, 999999999999.9999]) test(`accept numeric(16,4) quantity ${amount}`, () => assert.doesNotThrow(() => parseManualInventoryInput({ ...base(), availableQty: amount })))
for (const field of ["tenantId", "userId", "sourceType", "sourceProviderId", "source_payload"]) test(`reject server-owned field ${field}`, () => assert.throws(() => parseManualInventoryInput({ ...base(), [field]: "override" }), InventoryIntakeError))
for (const observedAt of ["2026-01-01T12:00:00", "2026-02-30T12:00:00Z", "2026-01-01T24:00:00Z", "0000-01-01T12:00:00Z", "2026-01-01T12:00:00.1234Z"]) test(`reject invalid timestamp ${observedAt}`, () => assert.throws(() => parseManualInventoryInput({ ...base(), observedAt }), InventoryIntakeError))
test("reject expected receipt offsets outside supported calendar years", () => assert.throws(() => parseManualInventoryInput({ ...base(), expectedAvailableAt: "9999-12-31T23:59:59-23:59" }), InventoryIntakeError))
test("reject year zero expected receipt dates", () => assert.throws(() => parseManualInventoryInput({ ...base(), expectedAvailableAt: "0000-01-01T12:00:00Z" }), InventoryIntakeError))
test("reject future observations without rejecting future expected receipts", () => {
	assert.throws(() => parseManualInventoryInput(base(), Date.parse("2025-01-01T00:00:00Z")), /future/)
	assert.doesNotThrow(() => parseManualInventoryInput({ ...base(), expectedAvailableAt: "2030-01-01T00:00:00Z" }))
})
test("timezone offsets normalize to the same observation", () => assert.equal(parseManualInventoryInput({ ...base(), observedAt: "2026-01-01T17:00:00+05:00" }).observedAt, base().observedAt.replace("Z", ".000Z")))
for (const body of [null, [], "text", { ...base(), freshness: null }, { ...base(), sku: "" }, { ...base(), locationCode: "x".repeat(101) }, { ...base(), currency: "gbp" }]) test(`reject invalid body ${JSON.stringify(body).slice(0, 50)}`, () => assert.throws(() => parseManualInventoryInput(body), InventoryIntakeError))
test("requires JSON and rejects oversized chunked bodies", async () => {
	await assert.rejects(() => readInventoryIntakeBody(new Request("https://example.test/api/inventory", { method: "POST", body: "{}" })), error => error.status === 415)
	await assert.rejects(() => readInventoryIntakeBody(new Request("https://example.test/api/inventory", { method: "POST", headers: { "content-type": "application/json" }, body: "x".repeat(16_385) })), error => error.status === 413)
})
test("parses valid JSON and rejects malformed JSON", async () => {
	const request = body => new Request("https://example.test/api/inventory", { method: "POST", headers: { "content-type": "application/json; charset=utf-8" }, body })
	assert.equal((await readInventoryIntakeBody(request(JSON.stringify(base())))).sku, "SKU")
	await assert.rejects(() => readInventoryIntakeBody(request("{")), error => error.status === 400)
})
test("role is checked before database access", async () => {
	await assert.rejects(() => recordManualInventory({ query() { throw Error("must not query") } }, { tenantId: "t", userId: "u", role: "viewer" }, base()), error => error.status === 403)
})

const databaseUrl = process.env.INVENTORY_INTAKE_TEST_DATABASE_URL
async function dbFixture(run) {
	const { Client } = await import("pg")
	const client = new Client({ connectionString: databaseUrl })
	await client.connect()
	const { randomUUID } = await import("node:crypto")
	const actor = { tenantId: randomUUID(), userId: randomUUID(), role: "owner" }
	await client.query("begin")
	try {
		await client.query("insert into tenant(id,name,slug) values($1,'Intake test',$2)", [actor.tenantId, actor.tenantId])
		await client.query("set local role axaty_app")
		await client.query("select set_config('app.tenant_id',$1,true)", [actor.tenantId])
		await run(client, actor)
	} finally { await client.query("rollback"); await client.end() }
}

test("Postgres: first count creates manual warehouse, preserves zero/unknown, records actor", { skip: !databaseUrl }, () => dbFixture(async (client, actor) => {
	const result = await recordManualInventory(client, actor, base())
	assert.equal(result.inserted, true)
	const { rows: [row] } = await client.query("select s.*,l.location_type,l.display_name from inventory_position_snapshot s join inventory_location l on l.id=s.location_id where s.id=$1", [result.snapshotId])
	assert.equal(row.location_type, "own_warehouse")
	assert.equal(row.source_type, "manual")
	assert.equal(Number(row.available_qty), 0)
	assert.equal(row.on_hand_qty, null)
	assert.equal(row.source_payload.enteredBy, actor.userId)
}))
test("Postgres: exact retries are idempotent and changed payloads conflict", { skip: !databaseUrl }, () => dbFixture(async (client, actor) => {
	const first = await recordManualInventory(client, actor, base())
	const repeated = await recordManualInventory(client, actor, { ...base(), observedAt: "2026-01-01T17:00:00+05:00" })
	assert.equal(repeated.snapshotId, first.snapshotId)
	assert.equal(repeated.inserted, false)
	for (const change of [{ availableQty: 1 }, { observedAt: "2026-01-02T12:00:00Z" }, { sku: "OTHER" }, { locationCode: "different" }, { freshness: "partial" }, { expectedAvailableAt: "2026-02-01T00:00:00Z" }]) {
		await assert.rejects(() => recordManualInventory(client, actor, { ...base(), ...change }), error => error.status === 409)
	}
	assert.equal((await client.query("select count(*)::int total from inventory_position_snapshot")).rows[0].total, 1)
}))
test("Postgres: later new reference appends and cannot overwrite the first count", { skip: !databaseUrl }, () => dbFixture(async (client, actor) => {
	const first = await recordManualInventory(client, actor, base())
	const next = await recordManualInventory(client, actor, { ...base(), sourceReference: "count-2", availableQty: 5 })
	assert.notEqual(first.snapshotId, next.snapshotId)
	assert.equal((await client.query("select count(*)::int total from inventory_position_snapshot")).rows[0].total, 2)
	assert.equal(Number((await client.query("select available_qty from inventory_position_snapshot where id=$1", [first.snapshotId])).rows[0].available_qty), 0)
}))
test("Postgres: inactive or differently named locations are never reactivated or renamed", { skip: !databaseUrl }, () => dbFixture(async (client, actor) => {
	await recordManualInventory(client, actor, base())
	await assert.rejects(() => recordManualInventory(client, actor, { ...base(), locationName: "Rename", sourceReference: "rename" }), error => error.status === 409)
	await client.query("update inventory_location set active=false")
	await assert.rejects(() => recordManualInventory(client, actor, { ...base(), sourceReference: "inactive" }), error => error.status === 409)
	await assert.rejects(() => recordManualInventory(client, actor, base()), error => error.status === 409)
	const { rows: [row] } = await client.query("select active,display_name from inventory_location")
	assert.equal(row.active, false)
	assert.equal(row.display_name, "Warehouse")
	assert.equal((await client.query("select count(*)::int total from inventory_position_snapshot")).rows[0].total, 1)
}))
test("Postgres: RLS and explicit tenant filter prevent cross-tenant location use", { skip: !databaseUrl }, () => dbFixture(async (client, actor) => {
	await recordManualInventory(client, actor, base())
	const { randomUUID } = await import("node:crypto")
	const otherTenant = randomUUID()
	await client.query("reset role")
	await client.query("insert into tenant(id,name,slug) values($1,'Other intake',$2)", [otherTenant, otherTenant])
	await client.query("set local role axaty_app")
	await client.query("select set_config('app.tenant_id',$1,true)", [otherTenant])
	const other = { ...actor, tenantId: otherTenant }
	await assert.rejects(() => recordManualInventory(client, other, { ...base(), locationName: undefined }), /locationName/)
	assert.equal((await client.query("select count(*)::int total from inventory_position_snapshot")).rows[0].total, 0)
	const result = await recordManualInventory(client, other, base())
	assert.equal(result.inserted, true)
}))
test("Postgres: uncommitted intake is invisible to another transaction and rollback removes it", { skip: !databaseUrl }, async () => {
	const { Client } = await import("pg")
	await dbFixture(async (client, actor) => {
		const result = await recordManualInventory(client, actor, base())
		const observer = new Client({ connectionString: databaseUrl })
		await observer.connect()
		try { assert.equal((await observer.query("select count(*)::int total from inventory_position_snapshot where id=$1", [result.snapshotId])).rows[0].total, 0) }
		finally { await observer.end() }
		await client.query("rollback")
		assert.equal((await client.query("select count(*)::int total from inventory_position_snapshot where id=$1", [result.snapshotId])).rows[0].total, 0)
	})
})

test("Postgres: concurrent exact retries serialize to the same committed snapshot", { skip: !databaseUrl }, async () => {
	const { Client } = await import("pg")
	const { randomUUID } = await import("node:crypto")
	const admin = new Client({ connectionString: databaseUrl }), first = new Client({ connectionString: databaseUrl }), retry = new Client({ connectionString: databaseUrl })
	const actor = { tenantId: randomUUID(), userId: randomUUID(), role: "admin" }
	await Promise.all([admin.connect(), first.connect(), retry.connect()])
	try {
		await admin.query("insert into tenant(id,name,slug) values($1,'Concurrent intake',$2)", [actor.tenantId, actor.tenantId])
		for (const client of [first, retry]) {
			await client.query("begin")
			await client.query("set local statement_timeout='5s'")
			await client.query("set local role axaty_app")
			await client.query("select set_config('app.tenant_id',$1,true)", [actor.tenantId])
		}
		const inserted = await recordManualInventory(first, actor, base())
		let completed = false
		const pending = recordManualInventory(retry, actor, base()).then(result => { completed = true; return result })
		await new Promise(resolve => setTimeout(resolve, 50))
		assert.equal(completed, false)
		await first.query("commit")
		const repeated = await pending
		assert.equal(repeated.inserted, false)
		assert.equal(repeated.snapshotId, inserted.snapshotId)
		await retry.query("commit")
		assert.equal((await admin.query("select count(*)::int total from inventory_position_snapshot where tenant_id=$1", [actor.tenantId])).rows[0].total, 1)
	} finally {
		await Promise.all([first.query("rollback"), retry.query("rollback")])
		await admin.query("delete from tenant where id=$1", [actor.tenantId])
		await Promise.all([admin.end(), first.end(), retry.end()])
	}
})

const localTypes = ["own_warehouse", "third_party_logistics", "prep_center", "supplier", "in_transit", "other"]
test("omitted type stays unspecified until creation for backwards-compatible existing-location callers", () => {
 assert.equal(parseManualInventoryInput(base()).locationType, null)
})
for (const locationType of localTypes) test(`manual parser accepts local type ${locationType}`, () => {
 assert.equal(parseManualInventoryInput({ ...base(), locationType }).locationType, locationType)
})
for (const locationType of ["amazon_fba", "amazon_awd", "WAREHOUSE", "", null, 1, true]) test(`manual parser rejects unsupported type ${String(locationType)}`, () => {
 assert.throws(() => parseManualInventoryInput({ ...base(), locationType }), error => error.status === 400)
})
test("manual JSON intake preserves explicit local type", async () => {
 const request = new Request("https://example.test/api/inventory", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...base(), locationType: "prep_center" }) })
 assert.equal(parseManualInventoryInput(await readInventoryIntakeBody(request)).locationType, "prep_center")
})
test("CSV service rejects requested location types before database access", async () => {
 await assert.rejects(() => recordCsvInventory({ query() { throw Error("must not query") } }, { tenantId: "t", userId: "u", role: "admin" }, { ...base(), locationType: "supplier" }), error => error.status === 400)
})
for (const locationType of localTypes) test(`Postgres: create ${locationType}, exact retry and omitted-type observation preserve it`, { skip: !databaseUrl }, () => dbFixture(async (client, actor) => {
 const request = { ...base(), locationType }
 const first = await recordManualInventory(client, actor, request)
 assert.equal((await client.query("select location_type from inventory_location where id=$1", [first.locationId])).rows[0].location_type, locationType)
 const retry = await recordManualInventory(client, actor, request)
 assert.equal(retry.inserted, false)
 assert.equal(retry.snapshotId, first.snapshotId)
 const omittedRetry = await recordManualInventory(client, actor, base())
 assert.equal(omittedRetry.snapshotId, first.snapshotId)
 const mismatch = locationType === "other" ? "supplier" : "other"
 await assert.rejects(() => recordManualInventory(client, actor, { ...request, locationType: mismatch }), error => error.status === 409)
 await assert.rejects(() => recordManualInventory(client, actor, { ...request, sourceReference: "type-change", locationType: mismatch }), error => error.status === 409)
 await recordManualInventory(client, actor, { ...base(), sourceReference: "next-count" })
 assert.equal((await client.query("select location_type from inventory_location where id=$1", [first.locationId])).rows[0].location_type, locationType)
 assert.equal((await client.query("select count(*)::int total from inventory_position_snapshot")).rows[0].total, 2)
}))
test("Postgres: CSV default creation remains own warehouse and existing local type is preserved", { skip: !databaseUrl }, () => dbFixture(async (client, actor) => {
 const first = await recordManualInventory(client, actor, { ...base(), locationType: "prep_center" })
 const observed = await recordCsvInventory(client, actor, { ...base(), sourceReference: "csv-existing" })
 assert.equal(observed.locationId, first.locationId)
 assert.equal((await client.query("select location_type from inventory_location where id=$1", [first.locationId])).rows[0].location_type, "prep_center")
 const created = await recordCsvInventory(client, actor, { ...base(), locationCode: "csv-new", sourceReference: "csv-new" })
 assert.equal((await client.query("select location_type from inventory_location where id=$1", [created.locationId])).rows[0].location_type, "own_warehouse")
}))
