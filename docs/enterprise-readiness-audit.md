# Enterprise readiness audit

Status: first pass complete. This document separates core MVP readiness from client-production hardening.

## Ready for MVP / sandbox operations

- Multi-tenant database model exists.
- Row-level security is enforced on tenant-scoped public tables.
- App database role is separate from owner role.
- Copilot uses a read-only/no-write contract.
- Amazon refresh tokens use encrypted vault storage.
- SP-API sandbox setup and one-tenant seed helper exist.
- Ads API backend seams exist but stay blocked until Amazon approval.
- Rules are deterministic JSONB definitions, not AI-written mutations.
- Approval queue and action worker preserve human approval before write-back.
- Live Ads write-back is dry-run by default and requires explicit live command.
- Run history, alerts, verification, audit logs and coverage surfaces exist.
- CI covers Python tests, DB tests, dbt build, web typecheck and web build.

## Still required before a paying client production launch

### Access and tenant control

- Complete production review for custom role scopes and tenant picker flows.
- Add tests for scope enforcement at every sensitive route, not only UI visibility.
- Decide whether tenant API keys are read-only forever or whether write scopes will exist later.

### Amazon integration evidence

- Paste SP-API sandbox smoke-test logs into #94.
- Keep Ads approval issue #8 open until Amazon grants access.
- After Ads approval, run profile discovery and read smoke before any write-back test.
- Capture Seller Central reconciliation evidence for marts before client sign-off.

### Write-back safety

- Keep live actions behind approval queue, idempotency and audit trail.
- Add mutating API routes only after RBAC, idempotency and audit tests exist.
- Prove live baseline reads for every Ads action type before enabling live write-back.

### Operations

- Define backup and restore procedure for Postgres.
- Add production environment checklist for secrets, domain, TLS, worker scheduling and alert routing.
- Add incident playbook for failed ingestion, stale data, auth expiry and accidental action failure.
- Add rate-limit monitoring around Amazon APIs.

### Data quality

- Reconcile Ads and SP-API marts against Seller Central reports.
- Keep economics incomplete flags visible until cost ledger data is loaded.
- Add expected freshness thresholds per dataset in production runbooks.

### Platform follow-ups

- React Native mobile app remains deferred until API boundary is stable.
- MCP support remains platform follow-up and must start read-only.
- Copilot Python runner service wiring can be added after deployment topology is clear.

## Current open blockers

- #8 — Amazon Ads API approval and live evidence.
- #94 — SP-API sandbox smoke test evidence.
- #40 — Full API boundary/write contracts.
- #24/#108 — Native mobile app.
- #37/#106 — MCP implementation.

## Recommendation

The repo is ready to continue sandbox/onboarding work, but not yet ready to hold a paying client in production until the external Amazon evidence, production ops checklist, and write-back safety tests are complete.
