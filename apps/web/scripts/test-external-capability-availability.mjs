import assert from "node:assert/strict"
import { registerHooks } from "node:module"
import test from "node:test"

const aliases = {
	"@/lib/external-capability-availability": new URL("../lib/external-capability-availability.ts", import.meta.url).href,
	"@/lib/queries-readiness": new URL("../lib/queries-readiness.ts", import.meta.url).href,
	"@/lib/db": "data:text/javascript,export const { query, withTenant } = globalThis.readinessFixture",
	"@/lib/session": "data:text/javascript,export const currentTenantId = () => 'session-tenant'",
	"next/server": "data:text/javascript,export const NextResponse = { json: body => body }",
}
const hooks = registerHooks({
	resolve(specifier, context, nextResolve) {
		return nextResolve(Object.hasOwn(aliases, specifier) ? aliases[specifier] : specifier, context)
	},
})
const { externalCapabilityAvailability } = await import("../lib/external-capability-availability.ts")
const plain = value => JSON.parse(JSON.stringify(value))

test("the five unimplemented capabilities distinguish provider and API requirements", () => {
	const rows = plain(externalCapabilityAvailability())
	assert.deepEqual(rows.map(row => [row.capability, row.status]), [
		["rank_sov", "EXTERNAL_DATA_REQUIRED"],
		["sponsored_brands", "WAITING_FOR_API_APPROVAL"],
		["sponsored_display", "WAITING_FOR_API_APPROVAL"],
		["amazon_marketing_cloud", "WAITING_FOR_AMC"],
		["amazon_dsp", "WAITING_FOR_API_APPROVAL"],
	])
	assert.ok(rows.every(r => !r.implemented && r.required.length === 2))
	assert.notDeepEqual(rows[1].required, rows[2].required)
})

test("catalog callers cannot change later availability snapshots", () => {
	const previous = externalCapabilityAvailability()
	previous[0].required.length = 0
	previous[0].implemented = true
	previous.pop()
	const next = externalCapabilityAvailability()
	assert.equal(next.length, 5)
	assert.equal(next[0].required.length, 2)
	assert.equal(next[0].implemented, false)
})

test("tenant health uses tenant context, preserves evidence and never promotes unimplemented features", async () => {
	const scopedClient = {}
	const dependencies = [{
		marketplace_id: "fixture-marketplace", module_key: "ppc",
		dependency_key: "amazon_ads", readiness_state: "LIVE_READY",
	}]
	const modules = [{ module_key: "ppc", visibility_state: "ENABLED" }]
	const sql = []
	globalThis.readinessFixture = {
		query: async (client, statement) => {
			assert.equal(client, scopedClient)
			sql.push(statement)
			return statement.includes("external_dependency_state") ? dependencies : modules
		},
		withTenant: async (tenant, callback) => {
			assert.equal(tenant, "session-tenant")
			return callback(scopedClient)
		},
	}
	try {
		const route = await import("../app/api/health/readiness/route.ts")
		const response = await route.GET()
		assert.equal(sql.length, 2)
		assert.equal(response.dependencies, dependencies)
		assert.equal(response.modules, modules)
		assert.ok(response.externalCapabilities.every(row => row.implemented === false))
		assert.equal(route.dynamic, "force-dynamic")
	} finally {
		hooks.deregister()
		delete globalThis.readinessFixture
	}
})
