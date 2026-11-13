import type { PoolClient } from "pg"
import { query, type TenantRole } from "@/lib/db"
import { isManualInventoryLocationType, type ManualInventoryLocationType } from "@/lib/inventory-location-types"

export class InventoryIntakeError extends Error {
	constructor(message: string, public status = 400) { super(message) }
}

const MAX_BODY_BYTES = 16_384
const QUANTITIES = ["onHandQty", "availableQty", "reservedQty", "inboundQty", "unsellableQty", "committedQty", "inTransitQty"] as const
const FRESHNESS = ["current", "stale", "partial", "unknown"] as const
const ALLOWED_FIELDS = new Set<string>(["locationCode", "locationName", "locationType", "sku", "sourceReference", "observedAt", "freshness", ...QUANTITIES, "expectedAvailableAt", "currency"])

type ManualInventoryInput = {
	locationCode: string; locationName: string | null; locationType: ManualInventoryLocationType | null; sku: string; sourceReference: string;
	observedAt: string; freshness: typeof FRESHNESS[number];
	quantities: (string | null)[]; expectedAvailableAt: string | null; currency: string | null;
}

export function assertManualInventoryRole(role: TenantRole) {
	if (role !== "owner" && role !== "admin") throw new InventoryIntakeError("Only owners and admins can record inventory.", 403)
}

export async function readInventoryIntakeBody(request: Request, maxBodyBytes = MAX_BODY_BYTES): Promise<unknown> {
	if (request.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json") {
		throw new InventoryIntakeError("Content-Type must be application/json.", 415)
	}
	const declaredLength = request.headers.get("content-length")
	if (declaredLength && Number(declaredLength) > maxBodyBytes) throw new InventoryIntakeError("Inventory request is too large.", 413)
	if (!request.body) throw new InventoryIntakeError("A JSON inventory observation is required.")
	const reader = request.body.getReader()
	const chunks: Uint8Array[] = []
	let size = 0
	try {
		while (true) {
			const { done, value } = await reader.read()
			if (done) break
			size += value.byteLength
			if (size > maxBodyBytes) {
				await reader.cancel()
				throw new InventoryIntakeError("Inventory request is too large.", 413)
			}
			chunks.push(value)
		}
	} finally { reader.releaseLock() }
	const bytes = new Uint8Array(size)
	let offset = 0
	for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
	try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) }
	catch { throw new InventoryIntakeError("Request must contain valid UTF-8 JSON.") }
}

function text(value: unknown, name: string, limit: number, optional = false): string | null {
	if (optional && (value === undefined || value === null)) return null
	if (typeof value !== "string" || !value.trim() || value.trim().length > limit || /[\u0000-\u001f\u007f]/.test(value)) {
		throw new InventoryIntakeError(`${name} must be nonempty text of at most ${limit} characters.`)
	}
	return value.trim()
}

function timestamp(value: unknown, name: string): string {
	if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,3})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value)) {
		throw new InventoryIntakeError(`${name} must be an ISO timestamp with seconds and a timezone.`)
	}
	const calendar = new Date(`${value.slice(0, 10)}T00:00:00Z`)
	const time = Date.parse(value)
	if (Number(value.slice(0, 4)) < 1 || !Number.isFinite(time) || !Number.isFinite(calendar.getTime()) || calendar.toISOString().slice(0, 10) !== value.slice(0, 10)) {
		throw new InventoryIntakeError(`${name} is not a valid date.`)
	}
	const normalized = new Date(time).toISOString()
	if (!/^(?!0000)\d{4}-/.test(normalized)) throw new InventoryIntakeError(`${name} must resolve to a year between 1 and 9999.`)
	return normalized
}

export function parseManualInventoryInput(value: unknown, now = Date.now()): ManualInventoryInput {
	if (!value || typeof value !== "object" || Array.isArray(value)) throw new InventoryIntakeError("An inventory observation object is required.")
	const body = value as Record<string, unknown>
	if (Object.keys(body).some(key => !ALLOWED_FIELDS.has(key))) throw new InventoryIntakeError("Unsupported inventory field. Tenant, actor and source are assigned by the server.")
	const locationType = body.locationType === undefined ? null : body.locationType
	if (body.locationType !== undefined && !isManualInventoryLocationType(locationType)) throw new InventoryIntakeError("locationType must be a supported local location type. Amazon FBA and AWD cannot be created through manual inventory.")
	const observedAt = timestamp(body.observedAt, "observedAt")
	if (Date.parse(observedAt) > now) throw new InventoryIntakeError("observedAt cannot be in the future.")
	const expectedAvailableAt = body.expectedAvailableAt === undefined || body.expectedAvailableAt === null ? null : timestamp(body.expectedAvailableAt, "expectedAvailableAt")
	const freshness = body.freshness === undefined ? "current" : body.freshness
	if (!FRESHNESS.includes(freshness as typeof FRESHNESS[number])) throw new InventoryIntakeError("Unsupported inventory freshness state.")
	const quantities = QUANTITIES.map(name => {
		const amount = body[name]
		if (amount === undefined || amount === null) return null
		if (typeof amount !== "number" || !Number.isFinite(amount) || amount < 0 || !/^\d{1,12}(?:\.\d{1,4})?$/.test(String(amount))) {
			throw new InventoryIntakeError(`${name} must be a nonnegative number below one trillion with at most four decimals, or null.`)
		}
		return String(amount)
	})
	const currency = body.currency === undefined || body.currency === null ? null : body.currency
	if (currency !== null && (typeof currency !== "string" || !/^[A-Z]{3}$/.test(currency))) throw new InventoryIntakeError("currency must be a three-letter uppercase code or null.")
	return {
		locationCode: text(body.locationCode, "locationCode", 100)!, locationName: text(body.locationName, "locationName", 200, true), locationType: locationType as ManualInventoryLocationType | null,
		sku: text(body.sku, "sku", 100)!, sourceReference: text(body.sourceReference, "sourceReference", 200)!,
		observedAt, freshness: freshness as typeof FRESHNESS[number], quantities, expectedAvailableAt, currency: currency as string | null,
	}
}

const REFERENCE_LOCK_SQL = `select pg_advisory_xact_lock(hashtextextended($1,0))`
const EXISTING_SNAPSHOT_SQL = `
	select s.id::text "snapshotId",s.location_id::text "locationId",l.active,
		(s.source_type=$17 and l.location_code=$3 and ($4::text is null or l.display_name=$4) and s.sku=$5
		 and s.observed_at=$6::timestamptz and s.freshness_state=$7
		 and s.on_hand_qty is not distinct from $8::numeric
		 and s.available_qty is not distinct from $9::numeric
		 and s.reserved_qty is not distinct from $10::numeric
		 and s.inbound_qty is not distinct from $11::numeric
		 and s.unsellable_qty is not distinct from $12::numeric
		 and s.committed_qty is not distinct from $13::numeric
		 and s.in_transit_qty is not distinct from $14::numeric
		 and s.expected_available_at is not distinct from $15::timestamptz
		 and s.currency is not distinct from $16::text
		 and ($18::text is null or l.location_type=$18)) matches
	from inventory_position_snapshot s join inventory_location l on l.id=s.location_id and l.tenant_id=s.tenant_id
	where s.tenant_id=$1 and s.source_type in ('manual','csv_import') and s.source_reference=$2
	for update of l`
const LOCATION_SQL = `select id::text id,active,display_name,location_type from inventory_location where tenant_id=$1 and location_code=$2 for update`
const CREATE_LOCATION_SQL = `insert into inventory_location(tenant_id,location_code,location_type,display_name)
	values($1,$2,coalesce($4::text,'own_warehouse'),$3) on conflict (tenant_id,location_code) do nothing returning id::text id`
const INSERT_SNAPSHOT_SQL = `insert into inventory_position_snapshot
	(tenant_id,source_reference,location_id,sku,source_type,observed_at,freshness_state,
	 on_hand_qty,available_qty,reserved_qty,inbound_qty,unsellable_qty,committed_qty,in_transit_qty,
	 expected_available_at,currency,source_payload)
	values($1,$2,$3,$4,$17,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb)
	on conflict (tenant_id,source_type,source_reference,location_id,sku,observed_at) do nothing
	returning id::text "snapshotId",location_id::text "locationId"`

type SnapshotResult = { snapshotId: string; locationId: string }

type InventoryActor = { tenantId: string; userId: string; role: TenantRole }

/** Shared by single counts and batches; acquire before reference or location locks. */
export async function lockManualInventoryTenant(client: PoolClient, tenantId: string) {
	await query(client, REFERENCE_LOCK_SQL, [JSON.stringify(["inventory-intake-tenant", tenantId])])
}

/** Caller owns a withTenant transaction: all locks last until commit. */
async function recordInventoryObservation<T extends "manual" | "csv_import">(
	client: PoolClient, actor: InventoryActor, value: unknown, sourceType: T,
) {
	assertManualInventoryRole(actor.role)
	const input = parseManualInventoryInput(value)
	if (sourceType === "csv_import" && input.locationType !== null) throw new InventoryIntakeError("CSV imports do not accept locationType. New CSV locations use own_warehouse.")
	const referenceValues = [actor.tenantId, input.sourceReference, input.locationCode, input.locationName, input.sku,
		input.observedAt, input.freshness, ...input.quantities, input.expectedAvailableAt, input.currency, sourceType, input.locationType]
	await lockManualInventoryTenant(client, actor.tenantId)
	await query(client, REFERENCE_LOCK_SQL, [JSON.stringify([actor.tenantId, input.sourceReference])])
	const existing = await query<SnapshotResult & { active: boolean; matches: boolean }>(client, EXISTING_SNAPSHOT_SQL, referenceValues)
	const result = (row: SnapshotResult, inserted: boolean) => ({ ...row, sourceReference: input.sourceReference, sourceType, inserted })
	if (existing.length) {
		if (existing.length !== 1 || !existing[0].matches) throw new InventoryIntakeError("This source reference already describes a different observation. Use a new reference.", 409)
		if (!existing[0].active) throw new InventoryIntakeError("This inventory location is inactive.", 409)
		return result({ snapshotId: existing[0].snapshotId, locationId: existing[0].locationId }, false)
	}
	let locations = await query<{ id: string; active: boolean; display_name: string; location_type: string }>(client, LOCATION_SQL, [actor.tenantId, input.locationCode])
	if (!locations.length) {
		if (!input.locationName) throw new InventoryIntakeError("locationName is required to create a new inventory location.")
		await query(client, CREATE_LOCATION_SQL, [actor.tenantId, input.locationCode, input.locationName, input.locationType])
		locations = await query(client, LOCATION_SQL, [actor.tenantId, input.locationCode])
	}
	const location = locations[0]
	if (!location || !location.active) throw new InventoryIntakeError("This inventory location is inactive.", 409)
	if (input.locationType && input.locationType !== location.location_type) throw new InventoryIntakeError("The location type differs from the existing location. Existing locations are never overwritten.", 409)
	if (input.locationName && input.locationName !== location.display_name) throw new InventoryIntakeError("The location name differs from the existing location. Existing locations are never overwritten.", 409)
	const rows = await query<SnapshotResult>(client, INSERT_SNAPSHOT_SQL,
		[actor.tenantId, input.sourceReference, location.id, input.sku, input.observedAt, input.freshness,
			...input.quantities, input.expectedAvailableAt, input.currency, JSON.stringify({ enteredBy: actor.userId, inputChannel: sourceType === "csv_import" ? "csv" : "manual" }), sourceType])
	if (!rows.length) throw new InventoryIntakeError("This observation already exists. Retry the same request to resolve its reference.", 409)
	return result(rows[0], true)
}


export async function recordManualInventory(client: PoolClient, actor: InventoryActor, value: unknown) {
	return recordInventoryObservation(client, actor, value, "manual")
}

/** Trusted CSV import path; callers cannot select a source through request fields. */
export async function recordCsvInventory(client: PoolClient, actor: InventoryActor, value: unknown) {
	return recordInventoryObservation(client, actor, value, "csv_import")
}
