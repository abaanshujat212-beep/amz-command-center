# External dependency and module readiness

`external_dependency_state` is the canonical tenant/marketplace dependency state. `module_state` separately records entitlement and navigation visibility; hiding a module never grants or revokes server authorization.

`LIVE_READY` requires persisted evidence source and timestamp. Backend validation further rejects documentation, fixtures and sandbox evidence as proof of production readiness. Authorized live evidence must still be scoped to the applicable tenant, marketplace, profile/API role and contract version.

All writes run inside tenant transactions, are protected by forced RLS and emit `readiness.transition` audit records. Secrets, tokens and raw authorization material must never be placed in `reason_code`, `metadata` or audit payloads.

## External expansion capabilities

The authenticated `GET /api/health/readiness` response includes `externalCapabilities`
alongside the existing tenant-scoped `dependencies` and `modules` arrays. This
catalog is a product-level explanation of what is unavailable, not a
tenant-level entitlement, Amazon capability proof, or authorization grant.

| Capability | Reported state | Before an implementation can be enabled |
| --- | --- | --- |
| Rank and Share of Voice | `EXTERNAL_DATA_REQUIRED` | Review a licensed provider or documented Amazon source, with observation provenance, freshness and scope. Catalog enrichment does not qualify. |
| Sponsored Brands | `WAITING_FOR_API_APPROVAL` | Verify the authorized profile/marketplace and the Sponsored Brands report contract independently. |
| Sponsored Display | `WAITING_FOR_API_APPROVAL` | Verify the authorized profile/marketplace and the Sponsored Display report contract independently. |
| Amazon Marketing Cloud | `WAITING_FOR_AMC` | Verify advertiser authorization, instance/scope and privacy review before any governed queries or activation. |
| Amazon DSP | `WAITING_FOR_API_APPROVAL` | Confirm enterprise access and complete the capability review before any integration. |

All five entries return `implemented: false`. A raw `LIVE_READY` dependency
or a visible module does not promote one of these entries. No metrics, provider
credentials, tenant identifiers or customer data are added to the catalog.
`EXTERNAL_DATA_REQUIRED` is a catalog display status, not a new value in the
database readiness enum. The catalog does not query or activate external services.
