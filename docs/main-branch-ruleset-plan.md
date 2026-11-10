# `main` branch protection plan

This document records the intended GitHub ruleset for `main`. It is a
configuration plan; it does not change repository settings. The issue that
requested this plan requires separate explicit authorization before any
repository-administration change.

## Proposed ruleset

| Setting | Value |
| --- | --- |
| Name | `protect-main` |
| Target | Branch `main` |
| Enforcement | Active |
| Pull requests | Required for all changes |
| Required checks | `Python static checks and unit tests`; `Migration and Postgres-backed tests`; `dbt build`; `Web typecheck and build` |
| Check freshness | Require the branch to be up to date with `main` before merge |
| Force pushes | Block |
| Branch deletion | Block |
| Administrator bypass | No bypass actors; administrators follow the same PR and CI requirements |

The repository currently merges work by squash, so linear history is consistent
with its workflow. This plan does not require a reviewer approval count: the
existing delivery process depends on green CI and could otherwise be blocked
when no second reviewer is available.

## Apply and verify after authorization

1. Create the ruleset in repository Settings → Rules → Rulesets.
2. Select the `main` branch and enter the settings above.
3. Select the four exact status-check contexts emitted by the CI workflow.
4. Save with no bypass actors.
5. Re-read the ruleset and branch protection state, then verify a test branch
   cannot push directly or force-push to `main`.

The current branch-protection read through the available GitHub credential
returned HTTP 403, so this plan does not claim to verify the repository's
existing administration settings. Confirm the live ruleset after an authorized
administrator applies it.
