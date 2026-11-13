# Manual inventory intake

Owners and admins can append observations with `POST /api/inventory` using an authenticated session and `Content-Type: application/json`. The session supplies tenant and actor identity. The server always stores `source_type=manual` and records the original actor as `source_payload.enteredBy`.

```json
{
  "locationCode": "warehouse-a",
  "locationName": "Warehouse A",
  "sku": "SKU-1",
  "sourceReference": "stock-count-2026-11-11-001",
  "observedAt": "2026-11-11T08:00:00Z",
  "availableQty": 0,
  "onHandQty": null,
  "inboundQty": 50,
  "expectedAvailableAt": "2026-11-20T08:00:00Z",
  "freshness": "current"
}
```

A missing location is created as `own_warehouse` only when `locationName` is supplied. Existing location types and names are preserved; a conflicting supplied name or an inactive location returns 409. Omitting the name lets an existing active location be used. This endpoint does not manage location metadata or reactivate locations.

The available quantity is the explicitly observed availability. Inbound, reserved, committed and in-transit quantities never increase it automatically. Supported quantity fields are `onHandQty`, `availableQty`, `reservedQty`, `inboundQty`, `unsellableQty`, `committedQty`, and `inTransitQty`. Omitted or null values remain unknown, and explicit zero stays zero. Values must be JSON numbers below one trillion with at most four decimal places. Optional `currency` is an uppercase three-letter code; `freshness` accepts `current`, `stale`, `partial`, or `unknown`.

`observedAt` requires a valid ISO timestamp with seconds and timezone, at most millisecond precision, and cannot be in the future. `expectedAvailableAt` is optional/null and can be in the future or reflect an overdue expected receipt. Both timestamps reject invalid calendar dates and year zero. Location code and SKU are at most 100 characters; location name and source reference are at most 200. The UTF-8 JSON body is limited to 16 KiB, including streamed bodies. Unsupported keys, including tenant, source or actor overrides, are rejected.

Use a new source reference for every new observation. Retrying the same normalized observation with the same reference returns the original snapshot with `inserted:false` and HTTP 200; the first insertion returns `inserted:true` and HTTP 201. A human source reference is shared by manual and CSV intake within its tenant; changing between manual and CSV source with the same reference is a conflict. A reference is unique within that namespace: reusing it with different quantities, SKU, location, observation time, expected time, freshness or currency returns 409. Concurrent manual counts and CSV batches serialize through a shared tenant transaction lock, then retain the reference/location locks until commit. No existing snapshot is overwritten.

Successful responses contain:

```json
{
  "snapshot": {
    "snapshotId": "uuid",
    "locationId": "uuid",
    "sourceReference": "stock-count-2026-11-11-001",
    "sourceType": "manual",
    "inserted": true
  }
}
```

Errors return `{ "error": "message" }` with 400 for invalid input, 401 for no session, 403 for insufficient role, 409 for conflicts/tenant selection, 413 for an oversized body, and 415 for the wrong content type.

## History privileges and migration rollback

Migration `0068_inventory_append_only_grants.sql` enforces the history boundary at the database role. Migration `0002_rls.sql` grants SELECT/INSERT/UPDATE/DELETE both to existing public tables and, through `ALTER DEFAULT PRIVILEGES`, to future public tables. The SELECT/INSERT grant in `0067` did not remove those broader defaults.

The additive migration explicitly revokes UPDATE, DELETE and TRUNCATE on snapshots from `axaty_app`, preserving SELECT/INSERT. It also revokes DELETE/TRUNCATE on locations because deleting a location would cascade its snapshot history, while preserving location SELECT/INSERT/UPDATE. Tenant-erasure cascades are unchanged. Existing clients that attempted to mutate inventory history will now receive permission errors and must append new observations instead.

The down migration deliberately restores the prior snapshot UPDATE/DELETE and location DELETE permissions; that rollback weakens history protection and should be used only as an explicit migration rollback. It does not grant TRUNCATE, which was not part of the historical defaults.

## Validation

From the repository root, after installing web dependencies:

```sh
node --test apps/web/scripts/test-inventory-intake.mjs
INVENTORY_INTAKE_TEST_DATABASE_URL="$DATABASE_URL" node --test apps/web/scripts/test-inventory-intake.mjs
pytest tests/test_inventory_intake_db.py
```

The Node suite executes the actual TypeScript validation/service through the installed TypeScript compiler. With the optional database URL it also verifies tenant RLS using `axaty_app`, exact/conflicting and concurrent retries, append-only behavior, inactive locations, actor provenance, and transaction visibility/rollback. Use an isolated migrated test database with an administrative login able to create test tenants and `SET ROLE axaty_app`; do not point it at production. The pytest database tests run the service's actual SQL in the required Postgres CI job.
