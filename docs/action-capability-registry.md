# Action Capability Registry

`packages/shared/action_capabilities.json` is the canonical cross-runtime registry consumed by Python workers and the web approval service. Unknown action/entity combinations are false-by-default.

Recommendation, approval, baseline read, apply, rollback and verification support are independent flags. A complete static entry is still not executable: runtime readiness must be `LIVE_READY` from the tenant-scoped #144 state and verification evidence must be `AUTHORIZED_LIVE_READ` or `AUTHORIZED_LIVE_WRITE` from the #146 contract model. Documentation, fixture, static-contract and sandbox evidence always fail closed.

Local diagnostics are explicitly recommendation-only and never leave the database.
