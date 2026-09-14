# Authoritative source freshness

Rule evaluation resolves freshness from tenant-scoped `sync_watermark` and the latest matching `pipeline_run`. Process time is never accepted as source evidence. Each rule scope declares its required persisted dataset.

Missing watermarks/runs, failed or partial runs, and loads older than the tenant guard threshold fail closed before candidate evaluation. The usable report date is capped at the settled cutoff. Diagnostics pass through the same resolver.

Canonical reason codes are `source_missing`, `source_failed`, `source_partial`, `source_stale`, and `source_unsettled`. Evidence is included in the rules pipeline-run detail and metrics snapshots for downstream recommendation explanations.
