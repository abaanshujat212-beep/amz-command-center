import type { PoolClient } from "pg"
import type { TenantRole } from "@/lib/db"
import { assertManualInventoryRole, InventoryIntakeError, lockManualInventoryTenant, parseManualInventoryInput, recordCsvInventory } from "@/lib/inventory-intake"

export const INVENTORY_CSV_JSON_BYTES = 800 * 1024
const CSV_BYTES = 128 * 1024
const QUANTITIES = ["onHandQty", "availableQty", "reservedQty", "inboundQty", "unsellableQty", "committedQty", "inTransitQty"] as const
const HEADERS = new Set<string>(["locationCode", "locationName", "sku", "sourceReference", "observedAt", "freshness", "expectedAvailableAt", "currency", ...QUANTITIES])
const REQUIRED = ["locationCode", "sku", "sourceReference", "observedAt"]

export class InventoryCsvError extends InventoryIntakeError {
	constructor(message: string, status = 400, public details: Record<string, unknown> = {}) { super(message, status) }
}

export function parseInventoryCsvRequest(value: unknown) {
	if (!value || typeof value !== "object" || Array.isArray(value)) throw new InventoryCsvError("An import request object is required.")
	const body = value as Record<string, unknown>
	if (Object.keys(body).some(key => key !== "mode" && key !== "csv") || (body.mode !== "preview" && body.mode !== "commit") || typeof body.csv !== "string") {
		throw new InventoryCsvError("Use only mode (preview or commit) and csv text. Tenant, actor and source are assigned by the server.")
	}
	return { mode: body.mode, csv: body.csv }
}

function records(csv: string) {
	if (new TextEncoder().encode(csv).byteLength > CSV_BYTES) throw new InventoryCsvError("CSV text must be at most 128 KiB.", 413)
	for (const character of csv) {
		const code = character.charCodeAt(0)
		if (character.length === 1 && code >= 0xD800 && code <= 0xDFFF) throw new InventoryCsvError("CSV must contain valid Unicode text.")
	}
	const source = csv.startsWith("\uFEFF") ? csv.slice(1) : csv
	const rows: { rowNumber: number; fields: string[] }[] = []
	let fields: string[] = [], field = "", state: "start" | "plain" | "quoted" | "closed" = "start", line = 1, rowNumber = 1
	const finish = () => {
		const emptyLine = fields.length === 0 && field === "" && state === "start"
		fields.push(field)
		if (!emptyLine) rows.push({ rowNumber, fields })
		if (rows.length > 101) throw new InventoryCsvError("CSV must contain at most 100 data rows.", 413)
		fields = []; field = ""; state = "start"
	}
	for (let i = 0; i < source.length; i += 1) {
		const character = source[i]
		if (state === "quoted") {
			if (character === '"') {
				if (source[i + 1] === '"') { field += '"'; i += 1 } else state = "closed"
			} else if (character === "\r" || character === "\n") {
				field += character
				if (character === "\r" && source[i + 1] === "\n") { field += "\n"; i += 1 }
				line += 1
			} else field += character
			continue
		}
		if (character === ",") { fields.push(field); field = ""; state = "start" }
		else if (character === "\r" || character === "\n") {
			finish()
			if (character === "\r" && source[i + 1] === "\n") i += 1
			line += 1; rowNumber = line
		} else if (character === '"' && state === "start") state = "quoted"
		else if (state === "closed" || character === '"') throw new InventoryCsvError(`Unexpected character around a quoted field at CSV line ${line}.`)
		else { field += character; state = "plain" }
	}
	if (state === "quoted") throw new InventoryCsvError(`Unclosed quoted field at CSV line ${rowNumber}.`)
	finish()
	return rows
}

function flat(input: ReturnType<typeof parseManualInventoryInput>) {
	return { locationCode: input.locationCode, locationName: input.locationName, sku: input.sku, sourceReference: input.sourceReference,
		observedAt: input.observedAt, freshness: input.freshness, expectedAvailableAt: input.expectedAvailableAt, currency: input.currency,
		...Object.fromEntries(QUANTITIES.map((name, index) => [name, input.quantities[index] === null ? null : Number(input.quantities[index])])) }
}

export function previewInventoryCsv(csv: string, now = Date.now()) {
	const parsed = records(csv)
	if (parsed.length < 2) throw new InventoryCsvError("CSV needs one header row and at least one data row.")
	const headers = parsed[0].fields
	if (new Set(headers).size !== headers.length) throw new InventoryCsvError("CSV headers must not be duplicated.")
	if (headers.some(header => !HEADERS.has(header))) throw new InventoryCsvError("CSV contains an unknown header. Use the documented camelCase fields.")
	if (REQUIRED.some(header => !headers.includes(header))) throw new InventoryCsvError(`Required CSV headers: ${REQUIRED.join(", ")}.`)
	const references = new Map<string, number[]>()
	const rows = parsed.slice(1).map(record => {
		const errors: string[] = []
		let values: ReturnType<typeof flat> | null = null
		if (record.fields.length !== headers.length) errors.push(`Expected ${headers.length} columns; received ${record.fields.length}.`)
		const body: Record<string, unknown> = {}
		for (let i = 0; i < headers.length; i += 1) {
			const name = headers[i], cell = record.fields[i] ?? ""
			if (QUANTITIES.includes(name as typeof QUANTITIES[number])) {
				const value = cell.trim()
				if (!value) body[name] = null
				else if (!/^\d{1,12}(?:\.\d{1,4})?$/.test(value)) errors.push(`${name} must be a nonnegative decimal below one trillion with at most four decimals.`)
				else {
					const [integer, fraction = ""] = value.split(".")
					const decimal = fraction.replace(/0+$/, "")
					const canonical = integer.replace(/^0+(?=\d)/, "") + (decimal ? `.${decimal}` : "")
					if (String(Number(value)) !== canonical) errors.push(`${name} cannot be represented without changing its decimal value.`)
					else body[name] = Number(value)
				}
			} else if (!cell.trim() && !REQUIRED.includes(name)) {
				if (name !== "freshness") body[name] = null
			} else body[name] = cell
		}
		const reference = typeof body.sourceReference === "string" ? body.sourceReference.trim() : ""
		if (reference) references.set(reference, [...(references.get(reference) ?? []), record.rowNumber])
		if (!errors.length) {
			try { values = flat(parseManualInventoryInput(body, now)) }
			catch (error) { if (error instanceof InventoryIntakeError) errors.push(error.message); else throw error }
		}
		return { rowNumber: record.rowNumber, valid: errors.length === 0, errors, values }
	})
	for (const row of rows) {
		const reference = row.values?.sourceReference ?? parsed.find(record => record.rowNumber === row.rowNumber)?.fields[headers.indexOf("sourceReference")]?.trim()
		if (reference && (references.get(reference)?.length ?? 0) > 1) {
			row.errors.push("sourceReference is duplicated within this CSV batch.")
			row.valid = false
		}
	}
	const validRows = rows.filter(row => row.valid).length
	return { mode: "preview" as const, valid: validRows === rows.length, totalRows: rows.length, validRows, errorRows: rows.length - validRows, rows }
}

/** All writes, including first warehouse creation, must share one withTenant transaction. */
export async function commitInventoryCsv(client: PoolClient, actor: { tenantId: string; userId: string; role: TenantRole }, csv: string) {
	assertManualInventoryRole(actor.role)
	const preview = previewInventoryCsv(csv)
	if (!preview.valid) throw new InventoryCsvError("CSV contains invalid rows; nothing was imported.", 422, { ...preview, mode: "commit" })
	await lockManualInventoryTenant(client, actor.tenantId)
	const rows = []
	let inserted = 0
	for (const row of preview.rows) {
		try {
			const snapshot = await recordCsvInventory(client, actor, row.values)
			rows.push({ rowNumber: row.rowNumber, snapshot })
			if (snapshot.inserted) inserted += 1
		} catch (error) {
			if (error instanceof InventoryIntakeError) throw new InventoryCsvError(`CSV row ${row.rowNumber}: ${error.message} Nothing was imported.`, error.status, { rowErrors: [{ rowNumber: row.rowNumber, errors: [error.message] }] })
			throw error
		}
	}
	return { mode: "commit" as const, totalRows: rows.length, inserted, unchanged: rows.length - inserted, rows }
}
