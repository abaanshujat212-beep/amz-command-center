# ADR-002: Rules are data, not code

- **Status:** accepted
- **Date:** 2026-08-20

## Context

PPC optimisation logic changes constantly — per client, per season, per product
margin. If each rule is a Python function, every threshold tweak becomes a code
change, a review and a deploy. Clients would also be unable to see why anything
happened to their account.

## Decision

Rules are rows in the `rule` table. The condition is a JsonLogic-shaped `jsonb`
expression, the action is a `jsonb` descriptor, and both are compiled to
parameterised SQL against the marts at evaluation time.

Thresholds are expressed **relative to `break_even_acos`**, never as absolute
ACOS numbers.

## Consequences

**Easy**

- New rule or new threshold: an INSERT/UPDATE, no deploy
- Per-tenant rules with no branching code
- The UI can render a rule as a readable sentence
- Every evaluation stores `metrics_snapshot`, so "why did this bid change in
  March?" is answerable a year later

**Hard**

- We must validate `condition_jsonb` against a whitelist of variables and
  operators. Arbitrary jsonb compiled into SQL is an injection risk; only known
  metric names and comparison operators are permitted, and values are always
  bound as parameters
- A malformed rule is a runtime error, not a compile error — hence a required
  dry-run period before `enabled=true`

**Deliberately excluded**

No machine-learned bidding. Amazon's 4 March 2026 Business Solutions Agreement
change restricts AI/ML use in third-party PPC tools. Deterministic,
human-readable, human-approved rules keep us compliant and keep clients able to
audit us.
