-- Persist the stronger human confirmation required before a non-reversible
-- provider mutation can enter the approved queue.
alter table action
  add column if not exists approval_confirmation text;

comment on column action.approval_confirmation is
  'Exact typed confirmation recorded at approval for capability-gated irreversible actions.';
