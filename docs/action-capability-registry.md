# Action Capability Registry

`packages/shared/action_capabilities.json` is the canonical cross-runtime registry consumed by Python workers and the web approval service. Unknown action/entity combinations are false-by-default.

Recommendation, approval, baseline read, apply, rollback and verification support are independent flags. A complete static entry is still not executable: runtime readiness must be `LIVE_READY` from the tenant-scoped #144 state and verification evidence must be `AUTHORIZED_LIVE_READ` or `AUTHORIZED_LIVE_WRITE` from the #146 contract model. Documentation, fixture, static-contract and sandbox evidence always fail closed.

Local diagnostics are explicitly recommendation-only and never leave the database.

Non-local actions that support approval and live apply but have `rollback_supported: false` cannot use the regular one-click path. They must declare an exact `confirmation_phrase` in this registry. The approval UI and API require that phrase, persist it on the action and in the decision audit record, and the live worker checks it again before calling Amazon. Exact keyword creation, negative exact/phrase keywords and negative ASIN targets each require a distinct phrase; these adds have no provider delete/compensation path and are not represented as rollback support. Local-only findings do not need a phrase because they never reach the provider worker.

For reversible live actions, rollback support means the Ads worker has a concrete restore path using the captured before value. Tests enumerate every registry entry marked reversible and exercise its rollback route. If an endpoint cannot safely restore its prior state, its capability must remain false and use an explicit confirmation policy instead.

Before every write, the worker reads the current provider value and compares it
with the approved baseline. Drift is persisted as a distinct audit outcome and
blocks the provider call. Approved rows are claimed with `FOR UPDATE SKIP LOCKED`
inside the worker transaction, so concurrent workers cannot dispatch
the same action simultaneously. Entity-creation requests are not blindly
retried after ambiguous provider errors; their destination duplicate check is
repeated before an operator can re-approve a retry.
