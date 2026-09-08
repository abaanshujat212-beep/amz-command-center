# AXATY API contract catalog

Status: MVP API boundary contract.

## Authentication model

- Browser routes use authenticated user sessions.
- Every request resolves an active tenant from `session.active_tenant_id`.
- API key support stores raw keys once and persists only hashes.
- Users can only enter tenants where they have membership.

## API key scopes

- `read` — default scope for KPI, history, opportunity, approval-list and verification reads.
- `approve` — sensitive scope for guarded approval/rejection contracts. Requires owner/admin route checks and audit logging.
- `write` — reserved sensitive scope for future write-capable tools. Disabled by default and must never directly mutate Amazon without the approval/worker path.

Sensitive scopes must show operator warnings when created and remain revocable from settings.

## Tenant isolation

- Server code must set tenant context before reading tenant data.
- Public tenant tables rely on row-level security.
- Mart reads must go through tenant-filtered copilot views, not direct `marts.*` access.
- Cross-tenant reads are not allowed.

## Current read endpoints

- `GET /api/dashboard` — KPI summary, alerts and dashboard data.
- `GET /api/history` — recent pipeline/action history.
- `GET /api/search-terms` — tenant-scoped search term performance.
- `GET /api/placements` — placement performance.
- `GET /api/economics` — SKU/unit economics and cost-ledger view.
- `GET /api/verification` — post-action verification scorecards.
- `GET /api/opportunities` — Keepa/product opportunity rows.
- `GET /api/sqp` — SQP opportunity rows.
- `GET /api/approvals` — pending approval queue.
- `GET /api/tenant/memberships` — authenticated user's tenant memberships.

## Current guarded POST endpoints

- `POST /api/copilot` — prompt boundary. Builds a validated no-write runner payload; T2/write-like prompts require confirmation and remain proposal-only.
- `POST /api/tenant/select` — selects an active tenant after membership validation.
- `POST /api/approvals/{id}/decision` — approves or rejects one proposal using shared guarded decision logic.

## Write safety policy

No API endpoint should directly mutate Amazon.

Allowed write pattern:

1. deterministic rule or operator creates/proposes an action;
2. owner/admin approves through the approval contract;
3. action worker applies later;
4. worker re-reads live value and aborts on drift;
5. audit log records the decision and worker outcome.

Any future mutating route must include:

- owner/admin or explicit scoped permission check;
- tenant-scoped execution;
- idempotency key where retries are possible;
- audit event with before/after payload;
- refusal for unsupported live action types;
- no provider secrets in request or response;
- tests for RBAC, expiry/replay and audit trail.

## API/MCP sensitive write scopes

Sensitive API/MCP write scopes are tracked in #124. They remain disabled by default unless an owner/admin deliberately creates scoped keys and accepts warning UI. Route-level RBAC, idempotency and audit checks are still required before any write-capable endpoint/tool can use those scopes.

## Mobile client contract

The mobile app should start with these stable routes:

- read dashboard KPIs;
- list alerts and history;
- list pending approvals;
- approve/reject through `/api/approvals/{id}/decision`;
- ask Copilot through `/api/copilot` without direct writes.

Native mobile remains deferred until this API boundary is stable.
