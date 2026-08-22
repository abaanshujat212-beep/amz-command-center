# ADR 005 — Placement scope: a diagnostic now, a modifier later

- Status: accepted
- Date: 2026-08-22
- Issues: #27 (this), #32 (the deferred half), #28 (diagnostics)

## Context

`flag_low_cvr_placement` shipped with `scope: "placement"`. Nothing in
`query.SCOPE_SOURCES` knew that scope, so `engine.py` recorded
`"flag_low_cvr_placement: scope 'placement' not wired yet"` and moved on.

That failure mode is the dangerous kind: the run succeeds, the log looks
healthy, the rule count in the UI still says 8, and the rule simply never fires.
It stayed that way for a whole milestone.

Two problems sat underneath it.

**1. There was no placement data, and no way to ask for it.** Placement is not a
separate Amazon report. It is the `spCampaigns` report requested with an extra
`groupBy`. `DATASETS` mapped a dataset name to a bare report-kind string, and
`create_report()` took no `group_by` at all, so the request could not be
expressed. A placement mart would have read from an empty table forever.

**2. The rule's action contradicted the rule's name.** It was called
`flag_...`, described as "recommend only", and carried
`{"type": "set_placement_modifier", "op": "add_pct", "delta_pct": -20}` — a real
mutation. Worse, `add_pct` needs a base: a placement modifier is a percentage on
top of whatever the campaign already has. That current value lives in campaign
config (`dynamicBidding.placementBidding`), which nothing ingests. Computing
"-20%" from an assumed 0% on a campaign where the seller had set +50% would not
be a smaller bid — it would be a silent overwrite of a deliberate decision.

## Decision

**Split the rule from its lever.**

1. **Placement becomes a first-class scope for reporting.**
   `stg_ads_sp_placement_daily` → `mart_ppc_placement_daily`, wired into
   `SCOPE_SOURCES`. Raw lands in its own table: placements partition the
   campaign, so summing the two grains double-counts spend and halves every
   ACOS.

2. **The entity is `campaign_id:placement`, not the campaign.** Cooldowns, the
   daily change limit and the engine's `claimed` set all key on `entity_id`. A
   campaign-level id would let a finding about top-of-search suppress a finding
   about the product page.

3. **The rule becomes a diagnostic (`action_type = 'flag'`, ADR 004).** It now
   matches its own name, needs no current value, and can actually run today.

4. **`placement_modifier_pct` is published as NULL** and remains the scope's
   write-target column. This is load-bearing, not laziness: a future `add_pct`
   rule resolves its base from that column, and a null base makes it refuse
   loudly instead of assuming zero.

5. **Economics are joined from `mart_ppc_campaign_daily`,** not re-derived. A
   campaign that looked profitable in one view and unprofitable in another would
   discredit both.

6. **The unmapped placement value warns.** `accepted_values` on `placement`
   deliberately omits `'unknown'` at warn severity. Amazon has spelled these at
   least two ways; if a third appears, the mapping degrades to `'unknown'` and
   the rule goes quiet — a dbt warning is how we find out instead of wondering
   why findings stopped.

7. **`placement_api_enum` is NULL where no modifier can exist.** Off-Amazon
   placement takes no multiplier. Null is "impossible", not "unknown", and must
   never be guessed into `PLACEMENT_REST_OF_SEARCH`.

## Alternatives rejected

- **Default the current modifier to 0%.** Amazon's default really is 0%, so this
  is right until the day it is catastrophically wrong. Apply-time drift
  detection would catch the mismatch, but only after a proposal was reviewed and
  approved on a false premise — the reason text would have lied to the approver.
- **Ingest campaign config now, keep the mutation.** Correct, and deferred to
  #32 rather than dropped. It needs a config dataset, a new raw table and a
  slowly-changing shape (a modifier is state, not a daily fact) — too much to
  attach to a wiring fix.
- **Delete the rule.** The finding is genuinely useful: a placement converting
  at a third of the account average is often the single largest waste in an
  account, and the seller can act on it manually in a minute.
- **Point the placement scope at `mart_ppc_campaign_daily`.** Would have made
  the rule "run" while comparing a campaign to the account average, i.e. a
  different rule wearing this one's name.

## Consequences

- All 11 catalog rules now have a wired scope.
  `test_every_catalog_rule_has_a_wired_scope` fails the build if that stops
  being true, which is the check that would have caught this on day one.
- `starter_rules.py` holds only change actions; every `flag` lives in
  `diagnostic_rules.py`. `test_starter_rules_are_all_change_actions` pins it.
- Nothing here has run. No `dbt build` has compiled the new models, and the
  placement raw table does not exist yet, so #27 stays open until
  `make migrate && dbt build && pytest` pass with output pasted into the issue.
