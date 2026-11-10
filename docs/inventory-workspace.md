# Inventory workspace

The page consumes the normalized camelCase snapshot contract introduced by PR #368.

`/inventory` is a read-only view of the active tenant's latest inventory observations and stock coverage. It is available under Products in desktop navigation and the mobile menu.

Filter by exact SKU, exact location code, and source freshness threshold. Pagination preserves the filters. Position evidence counts describe the visible page; the matching-position count spans the filtered result.

Each position keeps available stock separate from on-hand, reserved, committed, inbound, in-transit and unsellable quantities. Missing quantities display **Unknown**, including when other fields have a recorded zero. Source, observation time and expected availability remain visible.

Stock coverage is shown for the SKUs on the current page and aggregates **all active locations**. A location filter does not redefine the SKU-wide forecast. Blocked forecasts show their reasons and evidence instead of presenting days of supply or a stockout date as actionable. Forecast assumptions expose sales coverage, timestamps, confidence, seasonality and lead-time readiness.

The page does not create purchase orders, change ads, or import inventory. Those workflows retain their existing capability and approval gates.

## Validation

From `apps/web`, run:

```sh
node scripts/test-inventory-workspace.cjs
npm run typecheck
npm run build
```

The render check covers invalid filter rejection, filter-preserving pagination, unknown quantities, blocked forecasts, escaped source references, page-scoped evidence counts and empty states.
