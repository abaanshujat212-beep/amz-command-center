drop view if exists v_action_retry_status;
drop trigger if exists action_failure_retry_schedule on action;
drop function if exists schedule_action_failure_retry();
drop function if exists classify_action_failure(text);
drop index if exists idx_action_dead_letter;
drop index if exists idx_action_due_retry;
alter table action
  drop constraint if exists action_failure_classification_valid,
  drop constraint if exists action_replay_count_nonnegative,
  drop constraint if exists action_max_retry_attempts_valid,
  drop constraint if exists action_retry_count_nonnegative,
  drop column if exists replay_count,
  drop column if exists dead_letter_reason,
  drop column if exists dead_lettered_at,
  drop column if exists failure_classification,
  drop column if exists last_retry_at,
  drop column if exists next_attempt_at,
  drop column if exists max_retry_attempts,
  drop column if exists retry_count;
