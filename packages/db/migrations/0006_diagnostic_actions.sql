-- 0006_diagnostic_actions.sql
-- Adds the diagnostic action type: 'flag'.
--
-- WHY THIS EXISTS (see issue #28)
-- The plan called for three rules that diagnose rather than change:
--   * high impressions + low CTR   -> listing/image problem
--   * high CTR + low CVR           -> price/review problem
--   * ACOS above break-even        -> tell me, do not touch it
-- None of them could be stored: action.action_type's CHECK list had no member
-- for "I am only telling you something". The `alert` table from 0003 looks like
-- the home for these, but it has no writer and no link to the rule or the
-- metric snapshot that produced the finding, so a diagnosis stored there could
-- not be explained, approved, dismissed or scored later.
--
-- Decision: diagnostics live in `action` alongside changes, as action_type =
-- 'flag'. One queue, one audit trail, one approval UI. The difference between
-- "do this" and "look at this" is the type, not the table.
--
-- The risk this creates is obvious and is fenced off below: a row in `action`
-- looks applicable. A flag must never be sent to Amazon.

-- ------------------------------------------------- widen the action_type list
-- The 0003 CHECK is inline and therefore auto-named. Look it up instead of
-- assuming 'action_action_type_check' -- a wrong guess here fails the whole
-- migration, and with the ledger from 0005/ADR-003 that failure is loud.
do $$
declare
  cname text;
begin
  select conname into cname
  from pg_constraint
  where conrelid = 'action'::regclass
    and contype  = 'c'
    and pg_get_constraintdef(oid) like '%set_placement_modifier%';

  if cname is null then
    raise exception 'could not find the action_type check constraint on action';
  end if;

  execute format('alter table action drop constraint %I', cname);
end $$;

alter table action
  add constraint action_action_type_check
  check (action_type in ('set_bid','set_budget','pause','enable',
                         'add_negative_exact','add_negative_phrase',
                         'create_keyword','set_placement_modifier',
                         'flag'));

-- ------------------------------------------- a flag can never reach Amazon
-- Enforced in the database, not just in services/actions. Application code
-- gets refactored; a CHECK constraint does not quietly stop being true.
-- Allowed states for a diagnostic: it is waiting to be read, dismissed, or it
-- aged out. 'approved', 'applied', 'rolled_back' and 'failed' are meaningless
-- for a finding and would mean something tried to execute it.
alter table action
  add constraint action_flag_is_never_applied
  check (
    action_type <> 'flag'
    or (status in ('pending','rejected','expired')
        and applied_at is null
        and rolled_back_at is null)
  );

-- Open findings, newest first: the query the dashboard will run constantly.
create index if not exists idx_action_tenant_flags_open
  on action (tenant_id, requested_at desc)
  where action_type = 'flag' and status = 'pending';

comment on constraint action_flag_is_never_applied on action is
  'Diagnostics are recommend-only. See docs/adr/004-diagnostics.md and issue #28.';
