# PPC data dictionary: optimizer signals

Signal contract version `r05.1` is defined in `services/rules/optimizer_signals.py`. `REQUIRED_SIGNALS` identifies the core bid, match, volume, performance and freshness fields; `OPTIONAL_SIGNALS` identifies economics, volatility, placement, retail and rank context. It consumes daily rows at the source mart grain, then emits one snapshot per tenant, entity type, and entity ID for an inclusive date window. It counts source rows for coverage but only uses `is_settled = true` rows in metric calculations. Duplicate entity/day rows are rejected to prevent double counting.

## Required signal set

| Signal | Meaning | Normalization | Null and zero behavior | Provenance |
| --- | --- | --- | --- | --- |
| `current_bid` | Bid on the latest settled row | Latest settled value | Missing if latest settled bid is null or invalid | Daily mart relation and entity/window reference |
| `match_type` | Keyword or target match type | Lowercase stable value | Missing if absent; invalid if it changes inside the window | Daily mart relation and entity/window reference |
| `impressions`, `clicks` | Settled window volume | Sum of settled daily counts | Observed zero stays `0`; null source values produce `partial` or `missing` status | Daily mart relation and entity/window reference |
| `spend`, `sales`, `orders` | Settled window cost and 7-day attributed outcomes | Sum over settled rows | Observed zero stays `0`; absent source values are not replaced with zero | Daily mart relation and entity/window reference |
| `cpc` | Cost per click | Total spend / total clicks | Undefined when clicks are zero; missing if source totals are missing | Derived from settled spend and clicks |
| `acos` | Advertising cost / attributed sales | Total spend / total sales | Undefined when sales are zero | Derived from settled spend and sales |
| `roas` | Attributed sales / advertising cost | Total sales / total spend | Undefined when spend is zero | Derived from settled sales and spend |
| `freshness_days` | Age of the latest settled report date at the requested window end | Calendar day difference | Always present when a settled row exists | Latest settled report date |

An `observed` status means every contributing settled row had a usable value. A `partial` status includes the sum of known rows and records that some rows were unavailable; consumers must decide whether partial evidence is sufficient. `missing`, `undefined`, `insufficient_data`, and `invalid` are distinct states and never imply zero.

## Optional signals

Economics (`break_even_acos`, `contribution_margin_pct`) are optional and preserve missing/partial status. Within a settled window, the minimum observed value is used so that a higher margin estimate cannot hide the thinnest observed margin. `volatility_cpc_cv` is the population coefficient of variation of daily CPC and is emitted only with at least two daily values; partial coverage is marked. Placement modifier, retail (inventory, Buy Box, price), and organic/sponsored rank or share-of-voice values are not fabricated by the PPC mart. A future adapter may supply them only with `source`, `source_ref`, and `observed_at`; otherwise the signal is marked missing or invalid. Placement names normalize to `top_of_search`, `product_page`, `rest_of_search`, or `off_amazon`; share and Buy Box values use fractions from 0 through 1; rank is a positive position; inventory is days of supply; price uses the tenant marketplace currency; margin and break-even ACOS use ratios, with negative contribution margin preserved.

Target-level daily performance, retail inventory, rank, and share-of-voice are not currently available as canonical inputs. The contract accepts keyword and target entity identities, but a target snapshot must use a target mart relation supplied by its future adapter. Search-term rows are observations of traffic, not writable bid entities, so they are excluded from this bid contract.

This contract is an input schema only. It does not choose a target ACoS, calculate a bid, or authorize a live mutation.

It records the current modeled definitions and does not certify them against Seller Central. The R01.3 reconciliation and approved KPI truth table remain prerequisites for production use of optimizer recommendations.
