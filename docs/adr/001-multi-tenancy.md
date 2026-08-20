# ADR-001: Multi-tenancy via shared schema + tenant_id + RLS

- **Status:** accepted
- **Date:** 2026-08-20
- **Deciders:** ABAAN SHUJAAT

## Context

The system serves client Amazon accounts from day one — the first tenant is a
client's 5-6 year old UK Seller Central account, not our own. Options had to
balance strict data isolation against running on a single PC initially.

A leak between tenants is not a bug, it is a breach of someone else's business
data. At the same time, database-per-tenant on one machine would waste memory and
make migrations painful across a growing client list.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| Database per tenant | Hard isolation | Heavy on one PC, N migrations, slow onboarding |
| Schema per tenant | Decent isolation | Migration sprawl, cross-tenant reporting is painful |
| Shared schema + `tenant_id`, app-level filtering | Simple, cheap | One forgotten `WHERE` clause equals a breach |
| **Shared schema + `tenant_id` + Postgres RLS** | Cheap, single migration path, isolation enforced by the DB | Requires discipline: non-owner role, `FORCE RLS`, tenant context per transaction |

## Decision

Shared schema with `tenant_id` on every tenant-scoped table, isolation enforced
by Postgres Row Level Security with `FORCE ROW LEVEL SECURITY`. The application
connects as a non-owner role (`axaty_app`) and sets `app.tenant_id` as a
transaction-local setting on every request.

## Consequences

**Easy**

- Onboarding a client is an INSERT, not a provisioning job
- One migration path for all tenants
- A forgotten `WHERE tenant_id = ...` no longer leaks data — the policy still applies
- Cross-tenant internal reporting stays possible for the owner role

**Hard / requires discipline**

- The app role must never be superuser or table owner (owners bypass RLS without `FORCE`)
- Every code path must go through the tenant helper (`withTenant` / `set_tenant`)
- Connection pooling requires transaction-local settings, never session-level
- Composite indexes must lead with `tenant_id` or query plans degrade

**Revisit when**

- A client contractually requires physical data separation, or
- One tenant's volume justifies its own database

Until then, the isolation test (`tests/test_rls_isolation.py`) is a hard release
gate: cross-tenant reads must return zero rows and writes must be rejected.
