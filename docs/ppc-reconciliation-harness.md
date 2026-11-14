# PPC reconciliation harness

`infra/scripts/reconcile_ppc_exports.py` compares two normalized CSV exports over the same inclusive, settled date window. It is a read-only bridge for collecting repeatable evidence; it does not fetch Seller Central data, certify the modeled KPI definitions, or decide what tolerance is acceptable. Representative Seller Central exports and approved definitions/tolerances are still required before an actual R01.3 sign-off.

## Input contract

Both files must have exactly these columns, in any order:

```csv
report_date,grain,entity_id,placement,is_settled,currency,spend,ad_sales,ad_orders,total_sales,budget_amount
```

- `report_date` is ISO `YYYY-MM-DD`. In-window rows must have `is_settled=true`; out-of-window rows are excluded and counted.
- `grain` is `campaign`, `placement`, or `account`. `entity_id` identifies a campaign for campaign/placement rows and an account for account rows.
- Campaign rows are one row per campaign/day, with `spend`, `ad_sales`, and `ad_orders`. `budget_amount` is the campaign's daily budget snapshot; the harness takes each campaign's latest snapshot within the window and sums those snapshots. Do not repeat/allocate account totals on campaign rows.
- Placement rows are one row per campaign/day/normalized placement, with `spend`, `ad_sales`, and `ad_orders`. Placement names are `top_of_search`, `product_page`, `rest_of_search`, and `off_amazon`. If both campaign and placement rows are supplied, the harness requires them to cross-foot per source and KPI.
- Account rows are one row per account/day, with `total_sales`. They are the commerce-sales denominator for TACoS. Account rows and campaign rows should cover the same intended dates before interpreting TACoS.
- Amounts are non-negative or signed finite decimal values as supplied; orders must be integer decimals. Blank optional values remain missing, never zero. All rows must use the same uppercase three-letter currency.
- Duplicate `(date, grain, entity_id, placement)` keys are rejected. Aggregated ACoS is total campaign spend / total attributed ad sales; TACoS is total campaign spend / total account sales. A zero or missing denominator yields an unavailable ratio.

The harness cannot verify that the normalized source columns match Amazon's report definitions. Record the mapping from each source column and attribution window in the explicit KPI definitions. Do not normalize seller exports by guessing.

## Run

Pass one `--definition METRIC=TEXT` for each of `spend`, `ad_sales`, `ad_orders`, `acos`, `tacos`, and `budget_amount`. Definitions are copied to the output as provenance; the tool does not interpret them.

```sh
python infra/scripts/reconcile_ppc_exports.py \
  --application app-normalized.csv \
  --reference seller-central-normalized.csv \
  --start 2026-10-01 --end 2026-10-07 \
  --definition 'spend=settled campaign cost in source currency' \
  --definition 'ad_sales=settled 7-day attributed sales' \
  --definition 'ad_orders=settled 7-day attributed orders' \
  --definition 'acos=aggregate spend divided by aggregate attributed sales' \
  --definition 'tacos=aggregate spend divided by account total sales' \
  --definition 'budget_amount=sum of latest campaign daily budgets in window' \
  --output private/reconciliation.json
```

Without `--tolerances`, KPI comparisons are `unassessed`. An optional JSON file can declare per-metric absolute and/or relative thresholds; when both are provided both must pass. Example:

```json
{
  "spend": {"absolute": "0.01"},
  "acos": {"absolute": "0.001", "relative": "0.01"}
}
```

Only the explicitly configured metrics are assessed; missing thresholds stay unassessed. Placement thresholds use keys such as `placement.top_of_search.spend`, `placement.product_page.ad_sales`, or `placement.rest_of_search.ad_orders`. Placement outputs are itemized per placement, and an overall pass requires every reported placement comparison to have a passing tolerance. An unavailable metric is `incomplete`. Relative variance is absolute delta divided by absolute reference; with a zero reference, a relative-only bound cannot pass. The JSON report contains the inclusive window, file hashes, row/date coverage, definitions, aggregate values, variances and statuses. It is written atomically with mode `0600`. Keep source exports and reports private because they can contain account performance data.
