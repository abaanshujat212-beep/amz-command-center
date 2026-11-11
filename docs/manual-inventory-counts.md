# Manual stock counts

Owners and admins can open **Record a stock count** at `/inventory`. Other roles keep read-only inventory access. The inventory API independently checks permission before accepting a count.

Choose an existing active location code or enter a new code and warehouse name. New locations are created only as own warehouses; existing locations retain their name and type. Enter the SKU, when it was observed in UTC, and the quantities you know. A blank quantity remains unknown; an explicit `0` means confirmed zero. Available stock stays separate from reserved, committed, inbound and in-transit quantities.

The form creates a count reference and retains both the reference and observation time after a failed request. Retry the same count without changing that identity. A successful retry confirms the original count instead of adding a duplicate. **Start another count** creates a new reference and observation time, and clears the previous quantities.

After saving, the page refreshes and offers **View this SKU** in case the current filters exclude the observation. A new count does not create a purchase order, receive inbound units, or change ads.

## Validation

From the repository root:

```sh
node apps/web/scripts/test-manual-inventory-form.cjs
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

The script checks nullable versus zero quantities, existing/new location payloads, UTC dates, invalid input, stable retry identity, initial accessible markup and the server page's role gate. The form was also exercised in desktop and mobile Chromium against mocked save responses, including failed-save retry, successful refresh, duplicate notice, and starting a new count. That fixture test does not replace authenticated end-to-end API validation.
