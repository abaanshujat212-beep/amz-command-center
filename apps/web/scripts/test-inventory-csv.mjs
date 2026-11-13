import assert from "node:assert/strict"
import { randomUUID } from "node:crypto"
import { readFileSync } from "node:fs"
import test from "node:test"
import vm from "node:vm"
import ts from "typescript"

function load(path, imports) {
	const module = { exports: {} }
	vm.runInNewContext(ts.transpile(readFileSync(new URL(path, import.meta.url), "utf8"), { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }), {
		exports: module.exports, module, Date, TextEncoder, TextDecoder, Request, Response, Uint8Array,
		require: name => { assert.ok(name in imports, `Unexpected import ${name}`); return imports[name] },
	})
	return module.exports
}
const locationTypes = load("../lib/inventory-location-types.ts", {})
const intake = load("../lib/inventory-intake.ts", { "@/lib/inventory-location-types": locationTypes, "@/lib/db": { query: async (client, sql, params) => (await client.query(sql, params)).rows } })
const csvApi = load("../lib/inventory-csv.ts", { "@/lib/inventory-intake": intake })
const { parseInventoryCsvRequest, previewInventoryCsv, commitInventoryCsv } = csvApi
const header = "locationCode,locationName,sku,sourceReference,observedAt,availableQty,onHandQty"
const base = (reference = "csv-1", changes = {}) => ({ locationCode: "warehouse", locationName: "Warehouse", sku: "SKU", sourceReference: reference, observedAt: "2026-01-01T12:00:00Z", availableQty: "0", onHandQty: "", ...changes })
const encode = value => /[",\r\n]/.test(String(value)) ? `"${String(value).replaceAll('"', '""')}"` : String(value)
const document = (rows = [base()], headers = header) => [headers, ...rows.map(row => headers.split(",").map(name => encode(row[name] ?? "")).join(","))].join("\r\n")

test("preview supports BOM, CRLF, quoted commas and escaped quotes without writes", () => {
	const result = previewInventoryCsv("\uFEFF" + document([base("csv-1", { locationName: 'Warehouse, "A"' })]) + "\r\n")
	assert.equal(result.valid, true)
	assert.equal(result.totalRows, 1)
	assert.equal(result.rows[0].rowNumber, 2)
	assert.equal(result.rows[0].values.locationName, 'Warehouse, "A"')
	assert.equal(result.rows[0].values.availableQty, 0)
	assert.equal(result.rows[0].values.onHandQty, null)
})
test("preview retains blank unknown quantities and explicit observed zero", () => {
	const row = previewInventoryCsv(document([base("csv-1", { availableQty: "", onHandQty: "0.0000" })])).rows[0]
	assert.equal(row.valid, true)
	assert.equal(row.values.availableQty, null)
	assert.equal(row.values.onHandQty, 0)
})
test("canonical equivalent decimal lexemes are accepted without changing value", () => {
	const row = previewInventoryCsv(document([base("csv-1", { availableQty: "0002.5000" })])).rows[0]
	assert.equal(row.valid, true)
	assert.equal(row.values.availableQty, 2.5)
})
for (const value of ["-1", "NaN", "Infinity", "1e-999", "1.00001", "1000000000000", "999999999999.9992"]) test(`invalid decimal ${value} is rejected before lossy coercion`, () => {
	const row = previewInventoryCsv(document([base("csv-1", { availableQty: value })])).rows[0]
	assert.equal(row.valid, false)
	assert.ok(row.errors.length > 0)
})
test("duplicate normalized references mark both batch rows invalid", () => {
	const result = previewInventoryCsv(document([base("csv-1"), base(" csv-1 ")]))
	assert.equal(result.valid, false)
	assert.equal(result.errorRows, 2)
	assert.ok(result.rows.every(row => row.errors.some(error => error.includes("duplicated"))))
})
for (const headers of [header + ",sku", header + ",tenantId", "locationCode,sku,sourceReference"]) test(`reject duplicate/unknown/missing headers ${headers}`, () => assert.throws(() => previewInventoryCsv(document([base()], headers))))
for (const text of ["", header, header + '\nwarehouse,"unclosed', header + '\nware"house,Warehouse,SKU,ref,2026-01-01T00:00:00Z,0,', header + '\nwarehouse,"Warehouse" x,SKU,ref,2026-01-01T00:00:00Z,0,']) test("reject empty or malformed CSV structure", () => assert.throws(() => previewInventoryCsv(text)))
test("multiline quoted fields parse and receive clear manual-field validation with physical row numbers", () => {
	const result = previewInventoryCsv(document([base("csv-1", { locationName: "Warehouse\r\nA" }), base("csv-2")]))
	assert.equal(result.rows[0].valid, false)
	assert.equal(result.rows[0].rowNumber, 2)
	assert.equal(result.rows[1].rowNumber, 4)
	assert.equal(result.rows[1].valid, true)
})
test("quoted empty data records are invalid rows while truly blank lines are skipped", () => {
	const result = previewInventoryCsv(header + '\n""\n\n' + document().split("\r\n")[1])
	assert.equal(result.totalRows, 2)
	assert.equal(result.rows[0].rowNumber, 2)
	assert.equal(result.rows[0].valid, false)
	assert.equal(result.rows[1].rowNumber, 4)
	assert.equal(result.rows[1].valid, true)
})
test("wrong column count and missing required values produce row errors without generated identities", () => {
	const result = previewInventoryCsv(header + "\nwarehouse,Warehouse,SKU,ref\n" + document([base("", { observedAt: "" })]).split("\r\n")[1])
	assert.equal(result.valid, false)
	assert.equal(result.errorRows, 2)
	assert.ok(result.rows.every(row => row.values === null))
})
test("future or timezone-free timestamps are invalid observations", () => {
	for (const observedAt of ["9999-01-01T00:00:00Z", "2026-01-01T00:00:00"]) assert.equal(previewInventoryCsv(document([base("csv-1", { observedAt })])).valid, false)
})
test("row and UTF-8 byte limits are enforced", () => {
	assert.equal(previewInventoryCsv(document(Array.from({ length: 100 }, (_, i) => base(`ref-${i}`)))).totalRows, 100)
	assert.throws(() => previewInventoryCsv(document(Array.from({ length: 101 }, (_, i) => base(`ref-${i}`)))), error => error.status === 413)
	assert.throws(() => previewInventoryCsv("é".repeat(65_537)), error => error.status === 413)
	assert.throws(() => previewInventoryCsv("\ud800"))
})
test("request modes and fields are exact and tenant/source cannot be supplied", () => {
	assert.equal(parseInventoryCsvRequest({ mode: "preview", csv: document() }).mode, "preview")
	for (const body of [null, [], { mode: "write", csv: document() }, { mode: "preview", csv: document(), tenantId: "other" }, { mode: "commit", csv: document(), sourceType: "manual" }]) assert.throws(() => parseInventoryCsvRequest(body))
})
test("invalid batch and insufficient roles fail before querying", async () => {
	const client = { query() { throw Error("must not query") } }
	await assert.rejects(() => commitInventoryCsv(client, { tenantId: "t", userId: "u", role: "viewer" }, document()), error => error.status === 403)
	await assert.rejects(() => commitInventoryCsv(client, { tenantId: "t", userId: "u", role: "owner" }, document([base("csv-1", { availableQty: "bad" })])), error => error.status === 422 && error.details.rows[0].valid === false)
})

const databaseUrl = process.env.INVENTORY_INTAKE_TEST_DATABASE_URL
async function fixture(run) {
	const { Client } = await import("pg")
	const client = new Client({ connectionString: databaseUrl })
	await client.connect()
	const actor = { tenantId: randomUUID(), userId: randomUUID(), role: "admin" }
	await client.query("begin")
	try {
		await client.query("insert into tenant(id,name,slug) values($1,'CSV test',$2)", [actor.tenantId, actor.tenantId])
		await client.query("set local role axaty_app")
		await client.query("select set_config('app.tenant_id',$1,true)", [actor.tenantId])
		await run(client, actor)
	} finally { await client.query("rollback"); await client.end() }
}
test("Postgres: preview writes nothing; commit sets CSV provenance and retries unchanged", { skip: !databaseUrl }, () => fixture(async (client, actor) => {
	const csv = document([base("csv-1"), base("csv-2", { locationName: "", availableQty: "5" })])
	assert.equal(previewInventoryCsv(csv).valid, true)
	assert.equal((await client.query("select count(*)::int total from inventory_location")).rows[0].total, 0)
	const first = await commitInventoryCsv(client, actor, csv)
	assert.equal(first.inserted, 2)
	assert.equal(first.unchanged, 0)
	const again = await commitInventoryCsv(client, actor, csv)
	assert.equal(again.inserted, 0)
	assert.equal(again.unchanged, 2)
	assert.equal(again.rows[0].snapshot.snapshotId, first.rows[0].snapshot.snapshotId)
	const { rows } = await client.query("select source_type,source_payload,available_qty,on_hand_qty from inventory_position_snapshot order by source_reference")
	assert.ok(rows.every(row => row.source_type === "csv_import" && row.source_payload.enteredBy === actor.userId && row.source_payload.inputChannel === "csv"))
	assert.equal(Number(rows[0].available_qty), 0)
	assert.equal(rows[0].on_hand_qty, null)
}))
test("Postgres: a later row conflict rolls back newly created locations and all observations", { skip: !databaseUrl }, () => fixture(async (client, actor) => {
	await intake.recordManualInventory(client, actor, { ...base("already-used"), availableQty: 2, onHandQty: null })
	const csv = document([base("csv-new", { locationCode: "new-warehouse", locationName: "New warehouse" }), base("already-used")])
	await client.query("savepoint batch")
	try { await assert.rejects(() => commitInventoryCsv(client, actor, csv), error => error.status === 409 && error.details.rowErrors[0].rowNumber === 3) }
	finally { await client.query("rollback to savepoint batch") }
	assert.equal((await client.query("select count(*)::int total from inventory_position_snapshot")).rows[0].total, 1)
	assert.equal((await client.query("select count(*)::int total from inventory_location where location_code='new-warehouse'")).rows[0].total, 0)
}))
test("Postgres: manual and CSV references share a tenant namespace with source-aware conflicts", { skip: !databaseUrl }, () => fixture(async (client, actor) => {
	await commitInventoryCsv(client, actor, document())
	await assert.rejects(() => intake.recordManualInventory(client, actor, { ...base(), availableQty: 0, onHandQty: null }), error => error.status === 409)
	const other = randomUUID()
	await client.query("reset role")
	await client.query("insert into tenant(id,name,slug) values($1,'Other CSV',$2)", [other, other])
	await client.query("set local role axaty_app")
	await client.query("select set_config('app.tenant_id',$1,true)", [other])
	assert.equal((await client.query("select count(*)::int total from inventory_position_snapshot")).rows[0].total, 0)
	const result = await commitInventoryCsv(client, { ...actor, tenantId: other }, document())
	assert.equal(result.inserted, 1)
}))
test("Postgres: inactive locations still reject CSV intake", { skip: !databaseUrl }, () => fixture(async (client, actor) => {
	await commitInventoryCsv(client, actor, document())
	await client.query("update inventory_location set active=false")
	await assert.rejects(() => commitInventoryCsv(client, actor, document([base("csv-new")])), error => error.status === 409)
	assert.equal((await client.query("select count(*)::int total from inventory_position_snapshot")).rows[0].total, 1)
}))

test("Postgres: opposite-order imports and a manual count serialize without ref/location cycles", { skip: !databaseUrl }, async () => {
	const { Client } = await import("pg")
	const admin = new Client({ connectionString: databaseUrl }), importing = new Client({ connectionString: databaseUrl }), retrying = new Client({ connectionString: databaseUrl }), manual = new Client({ connectionString: databaseUrl })
	const actor = { tenantId: randomUUID(), userId: randomUUID(), role: "owner" }
	await Promise.all([admin.connect(), importing.connect(), retrying.connect(), manual.connect()])
	try {
		await admin.query("insert into tenant(id,name,slug) values($1,'Concurrent CSV',$2)", [actor.tenantId, actor.tenantId])
		for (const client of [importing, retrying, manual]) {
			await client.query("begin")
			await client.query("set local statement_timeout='5s'")
			await client.query("set local role axaty_app")
			await client.query("select set_config('app.tenant_id',$1,true)", [actor.tenantId])
		}
		const rows = [base("csv-a", { locationCode: "a", locationName: "A" }), base("csv-b", { locationCode: "b", locationName: "B" })]
		const first = await commitInventoryCsv(importing, actor, document(rows))
		let retryDone = false, manualDone = false
		const retry = commitInventoryCsv(retrying, actor, document([...rows].reverse())).then(async result => { await retrying.query("commit"); retryDone = true; return result })
		const count = intake.recordManualInventory(manual, actor, { ...base("manual-c", { locationCode: "a", locationName: "A" }), availableQty: 3, onHandQty: null }).then(async result => { await manual.query("commit"); manualDone = true; return result })
		await new Promise(resolve => setTimeout(resolve, 50))
		assert.equal(retryDone, false)
		assert.equal(manualDone, false)
		await importing.query("commit")
		const [again, counted] = await Promise.all([retry, count])
		assert.equal(first.inserted, 2)
		assert.equal(again.unchanged, 2)
		assert.equal(counted.inserted, true)
		assert.equal(counted.sourceType, "manual")
		assert.equal((await admin.query("select count(*)::int total from inventory_position_snapshot where tenant_id=$1", [actor.tenantId])).rows[0].total, 3)
	} finally {
		await Promise.all([importing.query("rollback"), retrying.query("rollback"), manual.query("rollback")])
		await admin.query("delete from tenant where id=$1", [actor.tenantId])
		await Promise.all([admin.end(), importing.end(), retrying.end(), manual.end()])
	}
})

test("CSV locationType header remains unsupported after manual taxonomy expansion", () => {
 assert.throws(() => previewInventoryCsv(document([base()], header + ",locationType")), /unknown header/)
})
