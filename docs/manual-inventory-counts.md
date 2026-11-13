# Manual stock counts

Owners and admins can open **Record a stock count** at `/inventory`. Other roles keep read-only inventory access. The inventory API independently checks permission before accepting a count.

Choose an existing active location code or enter a new code, location name and local type. New manual locations can be an own warehouse, third-party logistics (3PL), prep center, supplier, in transit or another local location. Own warehouse remains the default. Existing locations retain their name and type; the type selector applies only to a new named location. Amazon FBA and AWD locations cannot be created through this form. Enter the SKU, when it was observed in UTC, and the quantities you know. A blank quantity remains unknown; an explicit `0` means confirmed zero. Available stock stays separate from reserved, committed, inbound and in-transit quantities.

The form creates a count reference and retains both the reference and observation time after a failed request. Retry the same count without changing that identity. A successful retry confirms the original count instead of adding a duplicate. **Start another count** creates a new reference and observation time, and clears the previous quantities.

After saving, the page refreshes and offers **View this SKU** in case the current filters exclude the observation. A new count does not create a purchase order, receive inbound units, or change ads.

## Manual API compatibility

`POST /api/inventory` accepts optional `locationType` with one of `own_warehouse`, `third_party_logistics`, `prep_center`, `supplier`, `in_transit` or `other`. Omission defaults to `own_warehouse` only when creating a location; it does not constrain or change an existing location. An explicit type that differs from an existing location returns `409`, including when retrying an existing count reference. Amazon types, null and unsupported values are rejected.

CSV import is unchanged: `locationType` is not a supported CSV header. New CSV locations remain own warehouses, and observations against existing locations preserve their current type. The CSV service rejects attempts to supply a type through its trusted recording helper as well.

## Validation

From the repository root:

```sh
node apps/web/scripts/test-manual-inventory-form.cjs
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

The script checks nullable versus zero quantities, existing/new location payloads, UTC dates, invalid input, stable retry identity, initial accessible markup and the server page's role gate. The form was also exercised in desktop and mobile Chromium against mocked save responses, including failed-save retry, successful refresh, duplicate notice, and starting a new count. That fixture test does not replace authenticated end-to-end API validation.
