# Offline multi-SKU retail proposal gate (R12.3)

The pure `assess_retail_proposal` adapter builds on the one-product
`retail_readiness` evaluator. It has no database, provider or queue
integration. Even `retail_pass` is review-only, not approval or readiness
evidence. A `retail_pass` is a historical economics and current evidence
screen, not a quantitative post-change spend forecast or enqueue permission.

1. Classify exposure using the final guarded proposal, not the incoming rule.
   Preserve rejects from the existing rule/native gates. Descending or
   unchanged bids, budgets or modifiers, as well as pause, diagnostics and
   negative targeting do not require retail inputs. Missing baselines are
   not reductions. Activation and positive new targets are evaluated as
   increasing exposure.
2. Evidence must cover a complete, fresh prospective ad inventory for the
   exact proposal, tenant, advertiser profile, marketplace and currency.
   Bid/harvest scope uses the authoritative destination ad group; a campaign
   bid modifier or budget change uses the whole campaign. Activation requires
   evidence covering ads the action would make eligible. Deduplicate
   consistent ad/SKU identity, reject conflicting identity, and require
   evidence for every potentially affected SKU.
3. Validate genuinely current, attributable retail availability, listing
   sellability, Featured Offer and commercial-change history before using
   settled per-SKU spend/sales at the exact impact scope and performance
   window. Historical advertised-product rows and Featured Offer percentage
   never satisfy current evidence. Compare each SKU's attributed ACoS with
   the strictest effective ceiling; an unallocated campaign aggregate cannot
   substitute, even if otherwise favorable.

For eventual canonical integration, resolve the destination using trusted
server-side ad/entity data and obtain authoritative normalized sources,
rather than passing web/API fields through as attestations. Flags and
basis labels in this pure contract express inputs, not independently
verified provider evidence. Once authorized sources exist, evaluate after
canonical scope/destination resolution and generic/native checks and before
evaluation/action persistence. Record bounded reason codes rather than raw
provider data. Repeat identity, completeness, freshness and economic checks
at approval and immediately before application. Historical per-SKU ACoS is
not a forecast of the increase's impact; verify a proposal-specific exposure
bound before live readiness. Without provider/attribution proof, keep the
integration offline; do not use this fixture to change state or create an
alternate queue.
