-- 0009_action_decision_actor.sql
--
-- Rejections had no actor.
--
-- `action` carried `approved_by` / `approved_at` and nothing else, so a rejected
-- row recorded *that* it was rejected and never *who* rejected it. On a table
-- whose whole purpose is "a human authorised this change to a client's spend",
-- half the decisions were anonymous.
--
-- Reusing `approved_by` for rejections was the tempting one-line fix and the
-- wrong one: any count of approvals would then silently include refusals, and
-- the audit question "who approved this?" would answer with the name of the
-- person who refused it. Wrong numbers that look right are the failure mode this
-- project keeps paying for.
--
-- So: `decided_*` covers every decision, `approved_*` keeps meaning approval and
-- only approval. Both are written on approve; only `decided_*` on reject.

alter table action
  add column if not exists decided_by uuid,
  add column if not exists decided_at timestamptz,
  add column if not exists decision   text;

comment on column action.decided_by is
  'Who decided (approve or reject). Null when the system decided, e.g. expiry.';
comment on column action.decided_at is
  'When the decision was recorded. Set for approvals and rejections alike.';
comment on column action.decision is
  'approved | rejected. approved_by/approved_at stay approval-only so counts stay honest.';

alter table action
  drop constraint if exists action_decision_check;
alter table action
  add constraint action_decision_check
  check (decision is null or decision in ('approved', 'rejected'));

-- A decision is a verdict plus a time. An actor may be absent (the system can
-- expire an action) but a verdict without a timestamp is not a decision, it is a
-- half-written row.
alter table action
  drop constraint if exists action_decision_is_complete;
alter table action
  add constraint action_decision_is_complete
  check (
    (decision is null and decided_by is null and decided_at is null)
    or (decision is not null and decided_at is not null)
  );

-- Backfill.
--
-- `action` has FORCE ROW LEVEL SECURITY (0003), which applies to the table owner
-- too. An UPDATE here with no `app.tenant_id` set would match zero rows and
-- report success -- exactly the silent no-op this migration exists to prevent.
-- Superusers bypass RLS, but the runner must not depend on being one.
alter table action no force row level security;

update action
   set decided_by = approved_by,
       decided_at = approved_at,
       decision   = 'approved'
 where approved_at is not null
   and decided_at is null;

-- Pre-0009 rejections: the verdict is knowable from `status`, the actor is not,
-- and inventing one would be worse than leaving it null. `requested_at` is used
-- as the timestamp only to satisfy the completeness constraint; it is not a
-- claim about when the rejection happened.
update action
   set decision   = 'rejected',
       decided_at = coalesce(decided_at, requested_at)
 where status = 'rejected'
   and decision is null;

alter table action force row level security;

create index if not exists idx_action_tenant_decided
  on action (tenant_id, decided_at desc)
  where decided_at is not null;
