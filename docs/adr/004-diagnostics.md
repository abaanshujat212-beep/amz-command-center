# ADR 004: Diagnostics are actions with a type of their own

- Status: accepted
- Date: 2026-08-22
- Issue: #28

## Context

The plan specified eight starter rules. The code shipped eight starter rules.
The counts matched, so nothing looked wrong -- but three planned rules were
missing and three unplanned ones had taken their place. The missing three were
all of the same kind: they diagnose rather than change.

1. Many impressions, few clicks -> the listing loses the click (main image,
   title, price, review count).
2. Many clicks, few orders -> the detail page loses the sale (price, reviews,
   stock, wrong variation).
3. Spending above break-even -> report it, do not touch it.

The first was named in the plan as the product's differentiator. Every cheap
tool moves bids; none of them tell you that no bid will fix a bad photo.

They were not "forgotten" so much as unstorable: `action.action_type`'s CHECK
list contained only mutations, and `resolve_action()` raised on any type it did
not recognise. A diagnostic rule would have failed at run time.

## Decision

**Diagnostics are rows in `action` with `action_type = 'flag'`.**

The `alert` table from 0003 was the obvious alternative and was rejected: it
has no `rule_id`, no `evaluation_id` and no metrics snapshot, so a finding
stored there cannot be explained, dismissed, or scored later. It also has no
writer at all, which is its own problem (still open).

One queue, one audit trail, one review UI. "Do this" and "look at this" differ
by type, not by table.

Consequences, each fenced explicitly:

1. **A flag must never reach Amazon.** Enforced in the database
   (`action_flag_is_never_applied` in 0006), not only in application code:
   `status` is restricted to `pending | rejected | expired` and `applied_at`
   must stay null. Code gets refactored; a CHECK constraint does not quietly
   stop being true.
2. **A flag must carry no instruction.** `resolve_action()` rejects a flag that
   contains `op`, `factor`, `delta`, `delta_pct`, `value`, `match_type` or
   `level`. Otherwise a rule authored as `{"type": "flag", "op": "multiply",
   "factor": 0.5}` would read as harmless and still execute.
3. **Diagnostics skip the mutation guardrails.** Guardrails limit damage, and a
   finding causes none. Running them over diagnostics silences them exactly
   when they matter: `automation_enabled` is false by default, so the kill
   switch alone would mean a new tenant sees zero findings; and blast radius
   would suppress "30% of your keywords have terrible CTR", which is a true
   statement about the account, not a runaway rule.
4. **Diagnostics keep every data-quality guardrail.** Stale, unsettled and thin
   data still block. A confidently wrong recommendation costs more trust than
   no recommendation.
5. **Diagnostics do not claim entities.** The engine allows one mutating rule
   per entity per run; a flag neither respects nor consumes that claim, so a
   CTR finding cannot silently cancel a bid change on the same keyword.

## Thresholds are account-relative

All three compare against the account's own `account_ctr` / `account_cvr` /
`break_even_acos`, never a fixed number. A 0.3% CTR is normal for a broad
discovery term and alarming for a branded exact; an absolute threshold would be
noise in one account and silence in another. This required adding `account_ctr`
to `mart_ppc_keyword_daily` and to every scope block in `query.py`.

`flag_low_ctr_listing` sets `min_clicks = 0` on purpose. The rule exists to
find keywords that do not get clicks, so gating it on clicks would guarantee it
never fires. Impressions (>= 5000) carry the statistical weight instead, which
works because the thin-data guardrail blocks only when clicks *and* impressions
are both below their minimums.

## Alternatives rejected

- **Write to `alert`**: no rule/evaluation link, no snapshot, no writer.
- **A separate `finding` table**: a second queue and a second UI for something
  that shares approval, expiry and audit semantics with actions.
- **`action_type = 'none'` with a severity column**: makes "no action" a valid
  mutation, which is exactly the ambiguity the CHECK constraint should prevent.

## Status of the work

Code landed. Not closed: `flag_low_cvr_placement` (#27) still references the
unwired `placement` scope, and none of this has run against a real database
yet. See #31 for the closure rule -- pushed is not done.
