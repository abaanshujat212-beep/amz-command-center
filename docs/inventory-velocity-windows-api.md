# Inventory demand windows in the forecast API

`GET /api/inventory/forecast` now includes `assumptions.velocityWindows` for each inventory SKU. This read-only evidence augments the existing 30-day forecast gates; a complete 7-day window cannot make a sparse or blocked 30-day forecast ready.

The object has `7d`, `14d` and `30d` keys, each using this shape:

```json
{
  "windowDays": 7,
  "startDay": "2026-11-04",
  "endDay": "2026-11-10",
  "observedDays": 7,
  "missingDays": 0,
  "coverage": 1,
  "status": "complete",
  "unitsObserved": 35,
  "averageDailyUnitsObserved": 5,
  "invalidRows": 0,
  "numericRangeExceeded": false,
  "salesFreshness": "current",
  "salesLoadedAt": "2026-11-10T23:00:00.000000Z",
  "latestSalesDate": "2026-11-10"
}
```

Windows cover completed UTC dates, from UTC today minus the window length through UTC yesterday, inclusive. Today, future dates and observations older than the window are excluded. A database session timezone change does not move those boundaries. Raw entities for the same SKU/report date are summed before counting observed dates, so multiple ASIN rows never invent extra days of coverage.

Missing dates are unknown, not inferred zero sales. `unitsObserved` sums supplied completed dates; `averageDailyUnitsObserved` divides only by observed dates. Known zero is preserved. Without observations, both statistics are null, coverage is zero, and status is `no_data`. With some dates, status is `partial`; with all dates, it is `complete`. Coverage is observed dates divided by window days, rounded to four decimals.

A missing, malformed or negative unit value invalidates the whole included window, even when valid rows exist on that same date. Status becomes `invalid`, both statistics are null and `invalidRows` counts the offending raw rows. Observed-day coverage still describes date presence. An aggregate above JavaScript's maximum safe integer also produces `invalid`/null statistics and `numericRangeExceeded:true`, without falsely counting syntactically valid rows as malformed. These rows do not invalidate a shorter window that excludes their dates.

`salesFreshness` is independent of coverage status. It is `unknown` for no data or any future-dated load in that window, `stale` when its latest load exceeds the request's freshness threshold, and otherwise `current`. `salesLoadedAt` is that window's latest load timestamp, normalized to UTC; `latestSalesDate` is its latest included report date. A fresh load outside the 7-day window does not refresh the 7-day evidence. Historical evidence can remain visible when freshness or other forecast blockers prevent a projection.

The existing forecast fields retain the 30-day completeness, valid-history and sales-freshness gates. Unsafe 30-day quantities add `demand_numeric_range_exceeded`. Stale/partial/unknown inventory suppresses days-of-supply and stockout projections. An otherwise valid derived stockout date outside the four-digit calendar through `9999-12-31` adds `stockout_date_range_exceeded`, returns a null projection and zero confidence rather than throwing; demand-window evidence remains available.

## Verification

With normal web dependencies and an isolated migrated test database:

```sh
node --test apps/web/scripts/test-inventory-velocity-windows.mjs
pytest tests/test_inventory_velocity_windows_db.py tests/test_inventory_demand_db.py tests/test_inventory_forecast_db.py
```

The pytest database tests execute the actual forecast SQL, including UTC/session and year boundaries, same-day aggregation, invalid-versus-zero values, window-specific freshness, tenant filtering and numeric bounds. The Node suite executes the actual TypeScript mapper through the installed compiler, checking blocked evidence, prior ready behavior, stock freshness and unsupported projection ranges.
