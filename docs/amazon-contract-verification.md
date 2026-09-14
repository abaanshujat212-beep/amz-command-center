# Amazon contract verification

The endpoint catalog remains the sole source of network paths. `packages/shared/amazon_contracts.py` adds executable checks for HTTP methods, required Ads/SP-API headers, UK marketplace scope, report payload shape and evidence level.

Static tests and sanitized fixtures prove request construction only. They never prove account authorization, production data quality or mutation support and therefore cannot set a capability to `LIVE_READY`. Ads live evidence must retain advertiser profile scope; SP-API evidence must retain marketplace and authorized-role scope.

CI performs no real Amazon mutation. Authorized live smoke evidence is a separately approved operational step and must be persisted through the readiness model.
