# ADR 006 — System Copilot: a generated system map, not an authored prompt

- **Status:** accepted
- **Date:** 2026-08-22
- **Issue:** #33
- **Supersedes:** nothing

## Context

We want an in-product AI that can inspect the whole platform, answer questions about it
from live data, and draft changes for a human to approve.

The hard part is not the model. It is the model's picture of the system. Every migration,
every new rule, every renamed mart column changes what is true. An AI that answers from a
stale picture is worse than no AI, because it is confidently wrong about a system that
moves a client's money.

We also have a legal boundary that is not negotiable: Amazon's March 2026 Business
Solutions Agreement update restricts AI/ML in third-party bidding tools.

## Decision

### 1. The system map is generated and test-enforced, never authored

Every fact the copilot knows comes from the thing that defines it:

| Fact | Source of truth |
| --- | --- |
| tables, columns, RLS policies | `information_schema`, `pg_policies` |
| valid action types | the `action_action_type_check` constraint |
| rules | `rule_catalog.ALL_RULES` |
| wired scopes | `query.SCOPE_SOURCES` |
| guardrails | the `Guard` enum |
| migrations applied | the `schema_migrations` ledger |
| Amazon endpoints | `packages/shared/endpoints.py` |
| config keys | `.env.example` keys, never values |

No schema fact is duplicated into a prompt. `tests/test_system_map.py` fails when a new
action type, rule, scope or endpoint is added without appearing in the map. The map cannot
rot quietly; it can only rot loudly, in CI.

### 2. The endpoint catalog is a code path, not documentation

`packages/shared/endpoints.py` is the single definition of every Amazon endpoint we may
call — method, path, version, rate limit, burst, lookback window, required scope, and
whether it mutates the seller's account. **The real clients build their requests from it.**

The alternative — a document listing endpoints while `ads_api.py` calls them separately —
fails in one predictable way: the two drift, and the copilot quotes the document. Making the
catalog load-bearing means "the copilot knows every endpoint" is true by construction. If an
endpoint is missing from the catalog, the client cannot call it either, so the gap surfaces
as a failure instead of as a confident wrong answer.

### 3. Three capability tiers, gated separately

- **T0 read and explain.** SELECT-only, tenant-scoped, no Amazon access needed.
- **T1 draft config edits.** Rule thresholds, `tenant_settings`, cost-ledger rows — emitted
  as a reviewable diff plus the exact SQL, into the #22 approval queue. Never a silent write.
- **T2 Amazon-facing.** May only enqueue `action` rows as `pending`. Cannot approve, cannot
  apply, cannot call a mutating endpoint. Existing guardrails apply unchanged.

### 4. The copilot is never in the bid decision path

It explains what a deterministic rule decided, and it may draft a rule's *configuration* for
a human to approve. The decision itself stays in compiled SQL with a logged reason string.

This is a compliance boundary, not a preference. It also happens to be the better product:
a client can ask "why?" and get the rule, the thresholds and the numbers — not a paraphrase
of a model's intuition.

### 5. It reads through RLS, as a SELECT-only role

New role `axaty_copilot`: `SELECT` only, allowlisted tables, `statement_timeout`, row cap, no
DDL. It calls `set_tenant()` like every other caller. A copilot that could read across
tenants is a data breach with a chat interface.

Generated SQL is parsed and validated against an allowlist before execution — a single
tenant-filtered `SELECT`, nothing else. Prompting is not a security control.

### 6. Silence beats invention

If the map does not contain the answer, the copilot must say so. A plausible invented mart
column is the most expensive output this feature can produce, because it is indistinguishable
from a real one until someone acts on it.

## Consequences

- Adding an endpoint or an action type now costs a catalog entry. That friction is the point.
- The copilot is useless before `make migrate` and a seeded database. Accepted: it is an
  observability tool over a running system, not a substitute for one.
- T0 is buildable today with no Amazon access. T1 and T2 are blocked on #22 and #4.
- The copilot cannot edit source code, and we do not want it to. Configuration and content
  are reversible and tenant-scoped; source code in a service holding client credentials is
  not. Repo-level editing belongs to a local coding agent.

## Alternatives rejected

**Write the schema into a long system prompt.** Cheapest to start, guaranteed to rot, and it
rots invisibly — exactly the failure mode we have already been bitten by twice in this repo
(a rule whose scope was never wired, a doc claiming a dbt DAG that did not compile).

**Embed the whole repo and retrieve.** Answers questions about *code* well and questions
about *live state* badly. "Which rules fired last night" is not in the repo. Live state is
the interesting half.

**Give the model raw SQL access to Postgres.** One `UPDATE` away from an incident, and RLS
alone would not save us because a superuser connection bypasses it.

**Let it call Amazon directly.** Discards guardrails, the audit trail, approval, cooldowns
and blast radius — every protection we built — and walks straight into the BSA boundary.
