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
