# Alert operations

Operational alerts are surfaced in the dashboard and history page so MVP failures are visible without digging through logs.

## Alert sources

- Scheduler health checks persist `data_stale` and `pipeline_failed` alerts.
- Action worker failures persist `action_failed` alerts.
- Live Ads credential load failures persist `auth_expired` alerts.

## Dashboard behavior

- The Command Center shows open critical and warning alerts before KPI content.
- The no-data state also shows alerts so ingestion/auth failures are visible before marts are populated.
- The History page remains the detailed operational view for alerts and pipeline runs.

## Operating rules

- Treat `critical` alerts as blockers for live write-back.
- Resolve an alert only after the underlying run or credential issue has been fixed.
- Duplicate open alerts are intentionally skipped by source and entity reference.

## Operator alerts inbox

The **Operator alerts** link in the Decisions menu and Run history opens
`/alerts`. This is a read-only view of the existing open alert rows and their
canonical event time/source, not a new source of alert state. It includes
allowlisted Amazon authorization, ingestion and freshness, automation,
action failure, economics evidence and inventory blockers. The label and
recovery guidance come from an internal catalogue. The page never kicks
off a retry, changes a setting, resolves an event or sends a notification.

The view is explicitly tenant-wide because the alert schema does not yet
have a reliable account key across all producers. An account selector does not
make these alerts account-specific. An authenticated client may read
`GET /api/alerts?severity=warning&limit=25` for the active authorized tenant.
Severity is optional (critical, warning or info); limit is 1–50. The endpoint
has a larger-results indicator, is not a push or delivery API, and does not
return raw event titles, error details, payloads, external identifiers or links.

Locally check the response contract with
`cd apps/web && node --experimental-strip-types --test tests/operator-alerts.test.mjs`.
Tenant SQL predicates and membership gates are covered by the accompanying Python
source-contract tests. Device flows, live notification delivery, and unified
pending approvals and native platform work remain separate acceptance gates.
