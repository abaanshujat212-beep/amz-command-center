# Bounded inventory CSV import

Owners/admins can call `POST /api/inventory/import` with JSON `{ "mode": "preview", "csv": "..." }` or `{ "mode": "commit", "csv": "..." }`. Authentication supplies tenant and actor. Only these two request fields and modes are accepted. Preview validates text and rows without querying or changing inventory. Commit revalidates the supplied text and applies every row in one tenant transaction; any row conflict rolls back earlier observations and newly created warehouse locations.

## CSV contract

Required exact camelCase headers:

```csv
locationCode,sku,sourceReference,observedAt
```

Optional headers: `locationName`, `freshness`, `currency`, `expectedAvailableAt`, `onHandQty`, `availableQty`, `reservedQty`, `inboundQty`, `unsellableQty`, `committedQty`, `inTransitQty`.

```csv
locationCode,locationName,sku,sourceReference,observedAt,availableQty,onHandQty,inboundQty
warehouse-a,"Warehouse, A",SKU-1,count-001,2026-01-01T12:00:00Z,0,,20
warehouse-a,,SKU-2,count-002,2026-01-01T12:00:00Z,5,5,
```

No references or timestamps are generated. Reuse the exact file for a retry and use new references for new observations. Unknown/duplicate headers, wrong column counts and duplicate normalized source references are rejected. Required field and timestamp validation reuses the manual intake parser. The same reference cannot appear twice in one batch, even with identical values.

The CSV limit is 128 KiB of UTF-8 text and 100 nonempty data records, excluding the header. BOM, CRLF/LF/CR, quoted commas and escaped quotes are supported. True blank lines are ignored, but a quoted empty record is validated as a data row. Embedded quoted newlines are parsed correctly; existing inventory text-field restrictions may still reject their values with a row error. Row numbers identify physical starting lines, including multiline fields. Quotes must begin at the start of a field; non-delimiter characters after a closing quote are invalid CSV.

Blank quantities remain unknown/null; explicit zero remains zero. Nonblank quantities require unsigned decimal notation below one trillion with at most four decimals. Scientific notation, nonfinite values and extra precision are rejected before numeric conversion. Canonical decimal values must survive conversion without changing, so `0002.5000` is accepted as `2.5`, while an unrepresentable high-precision value is rejected. Observation timestamps need seconds and timezone, must be valid and cannot be future-dated. Optional blank metadata is omitted/null; blank freshness uses `current`.

The existing JSON reader keeps its 16 KiB default for single-count intake. This route uses an 800 KiB streaming JSON envelope limit to accommodate escaped CSV text, then enforces the separate decoded CSV limit. Both malformed UTF-8 and malformed JSON are rejected.

## Provenance, concurrency and atomicity

The server stores `source_type=csv_import`, the original authenticated `enteredBy` actor, and `inputChannel=csv`. It does not store raw file contents. Existing snapshots are never overwritten. Missing locations require a name and are created only as `own_warehouse`; existing location names/types and inactive status are preserved. Migration 0068's inventory history permissions remain in effect.

Single manual observations and CSV batches share a tenant-scoped transaction advisory lock, acquired before reference/location locks. This serializes competing imports/manual writes within one tenant and prevents batches in opposite row order from forming lock cycles. Other tenants use separate locks. The shared reference lookup covers manual and CSV sources: an exact CSV retry returns the existing snapshot, but changing source with the same reference is a conflict, even if quantities match. Existing duplicate legacy references are rejected conservatively.

Preview checks syntax and input values only. Existing references, location existence/name/activity and concurrent changes are checked again at commit. A valid preview therefore does not guarantee commit success. The caller must confirm the exact previewed text and preserve that text after a failed commit to retry safely.

## Responses

Preview returns HTTP 200:

```json
{"mode":"preview","valid":true,"totalRows":1,"validRows":1,"errorRows":0,"rows":[{"rowNumber":2,"valid":true,"errors":[],"values":{"locationCode":"warehouse-a","sku":"SKU-1","sourceReference":"count-001","observedAt":"2026-01-01T12:00:00.000Z"}}]}
```

Each normalized `values` object also contains optional metadata and all quantity fields as numbers/null; invalid rows may have null values. A commit containing input errors returns HTTP 422 with this same shape (`mode:"commit"`) plus `error`, with no writes. Header/syntax errors are 400, limits are 413, media type is 415, missing authentication is 401 and insufficient role is 403. Runtime row errors include `{ "error": "message", "rowErrors": [{ "rowNumber": 2, "errors": ["message"] }] }`, normally with 409 for conflicts; all writes are rolled back.

Successful commit returns HTTP 200 with `mode:"commit"`, `totalRows`, `inserted`, `unchanged`, and `rows:[{rowNumber,snapshot}]`. Snapshot fields match single intake, with `sourceType:"csv_import"`; inserted plus unchanged equals total rows. There is no partial-success mode.

## Verification

```sh
node --test apps/web/scripts/test-inventory-csv.mjs
INVENTORY_INTAKE_TEST_DATABASE_URL="$DATABASE_URL" node --test apps/web/scripts/test-inventory-csv.mjs
pytest tests/test_inventory_csv_db.py tests/test_inventory_intake_db.py
```

Use an isolated migrated database with an administrative fixture login that can create test tenants and set the `axaty_app` role. Tests cover preview without writes, provenance, actual RLS/permissions, exact/source-conflicting retries, all-or-nothing rollback, and competing opposite-order imports alongside manual intake.
