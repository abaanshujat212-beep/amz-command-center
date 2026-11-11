# CSV stock count import

Owners and admins can use **Import stock counts from CSV** on `/inventory`. The server independently checks authorization for both preview and import. Other roles remain read-only.

Select a UTF-8 CSV file or paste its contents. Files may contain a UTF-8 BOM, CRLF line endings and quoted fields. The maximum is 128 KiB and 100 nonempty data records. **Download CSV headers** supplies a header-only template, without example counts that could accidentally be imported.

Required exact column names:

- `locationCode`
- `sku`
- `sourceReference`: a reference you supply for each observation
- `observedAt`: the observation time, including its timezone

Optional columns are `locationName`, `freshness`, `currency`, `expectedAvailableAt`, `availableQty`, `onHandQty`, `reservedQty`, `committedQty`, `inboundQty`, `inTransitQty` and `unsellableQty`. Supply `locationName` when creating an own warehouse. Blank quantities remain unknown; explicit `0` is confirmed zero. Inbound or expected stock stays separate from available stock.

**Preview rows** checks the CSV without saving it. Review the counts, fields and row errors. Row numbers refer to the starting line in the original file, including quoted multiline records. Fix every error and preview again; changing text or selecting another file clears the old preview and confirmation.

An import requires a valid preview of the exact current text and the explicit confirmation checkbox. All rows are saved together. Runtime conflicts, such as a changed location or reused count reference, stop the whole batch and show errors. Failed requests retain the CSV and its observation identities so an exact retry can safely distinguish already-recorded counts from new ones. The UI never invents references or observation times.

Successful imports show new, already-recorded and total counts, then refresh the inventory page. Imported observations retain `csv_import` provenance. No purchase orders or ad actions are created.

## Validation

```sh
node apps/web/scripts/test-inventory-csv-ui.cjs
node apps/web/scripts/test-manual-inventory-form.cjs
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

The CSV script covers exact text/byte limits, header-only template, malformed preview rejection, row/count consistency, unknown versus zero, commit totals, and page role gating. Isolated Chromium desktop/mobile interaction tests also cover file decoding/BOM preservation, no automatic import, pending guards, preview invalidation, explicit confirmation, failed exact retry, success/refresh, duplicate results, invalid rows and UTF-8/size errors. Browser fixtures use mocked import responses; they do not replace authenticated API integration testing.
