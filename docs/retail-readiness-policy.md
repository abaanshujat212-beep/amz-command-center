# Retail readiness and commercial-change guard (R12.2/R12.3)

This is a local, offline evaluator over **trusted** scoped input. It is not
connected to ingest, the scheduler, worker, UI, an override route or Amazon.
The caller cannot use the evaluator to enable write capabilities.

- Require the exact tenant, marketplace, SKU and currency on snapshot, history
  and all events, plus source labels and timezone-aware timestamps. Explicit
  history coverage must include all change families back to the evaluation
  window start minus the longest stabilization interval, and be current under
  the policy. An empty list is meaningful only with actual complete coverage.
- Retain before/after values, source and effective timestamp in evaluation
  evidence for triggering events. Replay of the exact same event is harmless;
  ambiguous same-kind ordering, broken transition chain, malformed price,
  conflicting event IDs or stale coverage fail closed.
- Stabilization is elapsed time in UTC. Old data does not become suitable just
  because a cooldown is over: require post-change and post-cooldown evidence
  before using a window to support increased spend.
- Lost Buy Box, unsellable listing, low stock, low days of supply, disallowed
  lifecycle or no positive margin block spend increases. Missing data means
  low confidence and no increase, never an assumed zero or positive signal.
  A lower verified break-even ACoS tightens the configured cap; excess stock
  does not loosen it. Reduction proposals and action approval are not part of
  this evaluator.

## Open before integrating

#187 requires authorized SP-API/catalog source mappings, sanitized payload
fixtures and tenant-isolated persistence. Price/coupon contracts, lifecycle
history/audit, and the UI/approval path for authorized overrides are not
implemented here. Use durable per-signal provenance, authenticated source
coverage and settled performance before connecting this evaluator to actual
recommendations. No production behavior changes.

#189/#190 explicitly wait for verified Marketing Stream access and delivery.
No hourly samples, ingest worker, inferred data or pacing/daypart behavior
are introduced. Keep `WAITING_FOR_MARKETING_STREAM` until the existing
marketplace/account-scoped readiness criteria are met.
