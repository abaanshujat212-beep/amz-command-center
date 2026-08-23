-- Down for 0009.
--
-- Dropping these columns loses every rejection actor recorded since 0009 ran.
-- That is acceptable only because approvals keep their own approved_by /
-- approved_at, and audit_log holds a separate, append-only record of both
-- verdicts written by apps/web at decision time.

drop index if exists idx_action_tenant_decided;

alter table action
  drop constraint if exists action_decision_is_complete;
alter table action
  drop constraint if exists action_decision_check;

alter table action
  drop column if exists decision,
  drop column if exists decided_at,
  drop column if exists decided_by;
