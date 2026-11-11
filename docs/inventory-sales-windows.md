# Inventory sales evidence windows

Inventory stock coverage cards can display 7-, 14- and 30-day historical sales evidence supplied by the forecast API. Each window shows its completed UTC date range, observed/missing days, observed units and average units per observed day.

Missing dates are never treated as zero sales. An observed zero remains `0`; absent, invalid or unsupported quantities remain unknown. Partial history may show its observed-day average, with an explicit missing-day warning. Source freshness and load time are shown independently from completeness: complete history can still have a stale or unverified source.

These windows are historical evidence. They do not clear existing coverage warnings, change days of supply, or create reorder recommendations. Invalid rows or quantities outside supported precision suppress totals and averages. Older API responses without window evidence display **Evidence unavailable** instead of fabricated statistics.

## Validation

```sh
node apps/web/scripts/test-inventory-window-ui.cjs
node apps/web/scripts/test-inventory-workspace.cjs
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

Window tests cover missing/invalid evidence, UTC ranges, zero versus unknown, partial averages, invalidity overriding completeness, source timestamps, numeric precision limits and blocked-card messaging. Desktop/mobile browser checks use isolated rendered fixtures rather than a full signed-in application session.
