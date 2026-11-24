import { test } from "node:test"
import assert from "node:assert/strict"
import { operatorAlertFilters, OPERATOR_ALERT_KINDS, presentOperatorAlert } from "../lib/operator-alerts-contract.ts"

test("operator alert filters have safe bounds and one unambiguous severity", () => {
	assert.deepEqual(operatorAlertFilters(new URLSearchParams()), { severity: null, limit: 25 })
	assert.deepEqual(operatorAlertFilters(new URLSearchParams("severity=critical&limit=50")), { severity: "critical", limit: 50 })
	for (const input of ["limit=0", "limit=51", "limit=1.5", "limit=-1", "limit=01", "limit=1&limit=2", "severity=other", "severity=info&severity=warning"]) {
		assert.equal(operatorAlertFilters(new URLSearchParams(input)), null, input)
	}
})

test("each known blocker has evidence time, plain source, and an internal recovery target", () => {
	for (const kind of OPERATOR_ALERT_KINDS) {
		const mapped = presentOperatorAlert({ id: "row-id", kind, severity: "warning", occurred_at: new Date("2026-11-23T04:00:00Z"), source: "scheduler" })
		assert.equal(mapped.occurredAt, "2026-11-23T04:00:00.000Z")
		assert.equal(mapped.severity, "warning")
		assert.equal(mapped.source, "Scheduler")
		assert.ok(mapped.title && mapped.nextStep)
		assert.match(mapped.recovery.href, /^\/(?!\/)/)
	}
})

test("operator view never reuses stored title, payload, entity, or recovery fields", () => {
	const row = { id: "row-id", kind: "auth_expired", severity: "critical", occurred_at: new Date("2026-11-23T04:00:00Z"),
		source: "unknown diagnostics", detail: { private: "opaque-fixture" }, entity_ref: "opaque-fixture", title: "opaque-fixture",
		recovery: { href: "https://fixture.invalid" } }
	const mapped = presentOperatorAlert(row)
	assert.equal(mapped.recovery.href, "/settings/amazon")
	assert.equal(mapped.source, "Internal event")
	assert.doesNotMatch(JSON.stringify(mapped), /opaque-fixture|fixture\.invalid|unknown diagnostics/)
	assert.equal(presentOperatorAlert({ ...row, source: null }).source, "Legacy alert")
	assert.equal(presentOperatorAlert({ ...row, kind: "report_ready" }), null)
})
