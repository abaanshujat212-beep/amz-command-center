# Bid optimizer calculation core

`services/rules/bid_optimizer.py` is the pure R05.2 calculation layer over the R05.1 `BidSignalSnapshot`. It emits `proposed`, `hold`, or `blocked` with before/after bid, bounded component pressures, reason codes, explanation text, and resolved goal sources. It does not read the database, persist an action, or call Amazon.

## Fail-closed conditions

The calculator blocks when policy bounds are invalid, the current bid is missing or outside active bounds, required settled signals are absent/partial/invalid, sales conflict with recorded orders, spend is inconsistent with positive sales, or goals conflict. It holds without a bid change on stale or low-volume evidence, zero sales, missing break-even economics, missing target goals, or a configured profit floor without contribution-margin evidence. Partial/undefined signals are never converted to zero.

## Calculation

For positive settled ACoS and ROAS, the goal pressures are `tanh(log(target_acos / observed_acos))` and, when target ROAS is supplied, `tanh(log(observed_roas / target_roas))`. If both goals exist, they must be reciprocal within 5%, and their pressures are averaged. The economic pressure is `tanh(log(break_even_acos / observed_acos))`; if a profit floor is configured, its pressure is `tanh(2 * (contribution_margin_pct - profit_floor))`.

Without a profit floor, the combined score is `0.67 * goal_pressure + 0.33 * economics_pressure`. With a profit floor, it is `0.55 * goal_pressure + 0.30 * economics_pressure + 0.15 * profit_floor_pressure`. An exceeded ACoS ceiling caps the score at a negative ceiling pressure, so performance above that ceiling cannot result in a bid increase.

Volume weight is `min(1, sqrt(clicks / (4 * min_clicks)))`. CPC stability weight is `1 / (1 + volatility_cpc_cv)` when volatility is observed and `0.75` when it is unavailable. The requested relative movement is the combined score multiplied by maximum change, volume weight and stability weight. The result is clamped to tenant bid bounds and rounded to currency precision (two decimals); a rounded no-op is returned as `hold`.

This is an original deterministic heuristic with visible intermediate values. Its thresholds and blending weights are policy choices, not Amazon recommendations or guarantees. R01.3 Seller Central reconciliation remains required before production use.
