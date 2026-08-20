# ADR-000: <short decision title>

- **Status:** proposed | accepted | superseded by ADR-XXX
- **Date:** YYYY-MM-DD
- **Deciders:** 

## Context

What problem forced a decision? Constraints that matter (Amazon API limits, client account,
single-PC hosting, compliance).

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| A | | |
| B | | |

## Decision

What we chose, in one sentence.

## Consequences

- What becomes easy
- What becomes hard
- What we must revisit later, and the trigger for revisiting

## Planned ADRs

- ADR-001 Multi-tenancy model (shared schema + `tenant_id` + RLS)
- ADR-002 Stack selection (Next.js, Postgres, dlt, dbt, Prefect)
- ADR-003 Ingestion strategy (watermarks, 95-day window, rolling re-ingest)
- ADR-004 Rules engine (JSONB + SQL, no AI bidding)
- ADR-005 Action engine (approval, audit, rollback)
