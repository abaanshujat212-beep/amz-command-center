# `main` branch protection status

This document records the live GitHub ruleset read for `main` on 2026-11-13.
It is documentation only and does not change repository settings.

## Verified ruleset

| Setting | Value |
| --- | --- |
| Name | `Protect main` (ruleset 26955622) |
| Target | Branch `main` |
| Enforcement | Active |
| Pull requests | Required for all changes |
| Required checks | `Python static checks and unit tests`; `Migration and Postgres-backed tests`; `dbt build`; `Web typecheck and build` |
| Check freshness | Strict; branch must be up to date with `main` |
| Force pushes | Blocked by non-fast-forward rule |
| Branch deletion | Blocked |
| Administrator bypass | No bypass actors; current user cannot bypass |
| Required approvals | 0 |
| Allowed merge methods | Merge, squash, and rebase |

The live ruleset also does not require code-owner review, last-push approval,
or review-thread resolution. `dismiss_stale_reviews_on_push` is false. The
repository's earlier plan described squash as its merge convention, but the
live ruleset allows all three merge methods.

## Verification limits

The ruleset API confirms the active configuration and its rules. This read-only
check did not attempt a direct push or force push to `main`; enforcement of
those operations is inferred from the configured pull-request, deletion, and
non-fast-forward rules.
