# External dependency and module readiness

`external_dependency_state` is the canonical tenant/marketplace dependency state. `module_state` separately records entitlement and navigation visibility; hiding a module never grants or revokes server authorization.

`LIVE_READY` requires persisted evidence source and timestamp. Backend validation further rejects documentation, fixtures and sandbox evidence as proof of production readiness. Authorized live evidence must still be scoped to the applicable tenant, marketplace, profile/API role and contract version.

All writes run inside tenant transactions, are protected by forced RLS and emit `readiness.transition` audit records. Secrets, tokens and raw authorization material must never be placed in `reason_code`, `metadata` or audit payloads.
