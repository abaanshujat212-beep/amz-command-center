# ADR-007: Shared identity with channel-specific commerce adapters

- **Status:** accepted
- **Date:** 2026-09-15
- **Deciders:** AXATY engineering
- **Issue:** #264

## Context

AXATY currently implements an Amazon Commerce OS. A future product may offer other
commerce operating systems, including Daraz, under one login. The identity and workspace
layer must permit that future without placing speculative channel fields in today's Amazon
schema or allowing one channel's capabilities to authorize another.

Tenant isolation remains the boundary defined by ADR-001. A workspace may authorize a user
to navigate several business tenants, but it does not merge those tenants or bypass their
RLS and RBAC contexts.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| Add Daraz fields to current Amazon tables now | Appears quick | Speculative schema, mixed semantics, unsafe capability assumptions |
| Build entirely separate identity systems per channel | Strong isolation | Duplicate login, membership, billing and workspace concepts |
| **Share identity/workspace; isolate channel adapters and domains** | One login without capability leakage | Requires explicit adapter contracts and context validation |

## Decision

Share only identity, workspace membership, configurable entitlements and authorized
business-context navigation. Keep channel account records, credentials, API clients, raw
and normalized data, readiness evidence, rules, capabilities, actions and audit semantics
inside explicit channel adapters/domains.

Amazon is the only implemented channel. This ADR creates no Daraz tables, endpoints,
credentials, rules or implementation backlog.

### Shared platform boundary

The shared layer may represent:

- user identity;
- workspace membership and workspace roles;
- business-tenant membership;
- commercial entitlements and limits;
- active context identifiers;
- generic channel identifier and adapter registration metadata.

The shared layer must not infer that access to a workspace grants access to every tenant,
channel account, marketplace or advertising profile. Each context change is revalidated
server-side and then enters the selected tenant's normal RLS/RBAC transaction boundary.

### Channel-specific boundary

Each channel adapter owns its own:

- authorization and encrypted credentials;
- API endpoint catalog and version support;
- marketplace/account/profile identifiers;
- ingestion and source-freshness evidence;
- raw, staging and mart schemas;
- deterministic rules and domain semantics;
- Action Capability Registry entries;
- approval, worker, verification and provider-error mapping.

An adapter cannot reuse another channel's readiness evidence or capability decision.
Unknown channel/action pairs fail closed. Browser and AI clients cannot call channel
mutation APIs directly; supported writes continue through capability, approval, worker,
live reread, drift, audit and verification controls.

### Read and AI context

A read request must carry an authorized tenant and channel context. Cross-account portfolio
reads coordinate separate tenant-governed reads and combine typed summaries only; they do
not introduce an unrestricted cross-tenant SQL role.

AI receives the same revalidated context and grounded source contract. It cannot infer a
channel, capability or external readiness state from prose, prompts or another adapter.

## Consequences

- A future channel can reuse login, workspace and entitlement infrastructure.
- Channel onboarding requires an explicit adapter, schemas, readiness states, capability
  entries and tests before any operation is exposed.
- Amazon code remains free of speculative Daraz fields.
- Common UI may render adapter-neutral identity and readiness states, while domain screens
  and writes remain channel-specific.
- Cross-channel analytics, if approved later, must consume governed summaries rather than
  blend raw tenant/channel rows.

## Rejected shortcuts

- Storing all agency clients in one tenant.
- Treating a brand as automatically equivalent to a tenant.
- A universal credential or endpoint table with channel-dependent nullable columns.
- Reusing Amazon capability support as evidence for another channel.
- Adding placeholder Daraz schemas or simulated provider readiness.

## Revisit when

A second commerce channel has an approved product specification, real authorization model,
source contracts and implementation backlog. That work must propose its own adapter ADR and
cannot weaken ADR-001, the false-by-default capability registry or the approval/worker audit
chain.
