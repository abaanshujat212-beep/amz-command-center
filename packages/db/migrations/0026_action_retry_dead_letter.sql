-- 0026_action_retry_dead_letter.sql
-- Durable, bounded retry scheduling and dead-letter state for action failures.

alter table action
  add column if not exists retry_count integer not null default 0,
  add column if not exists max_retry_attempts integer not null default 3,
  add column if not exists next_attempt_at timestamptz,
  add column if not exists last_retry_at timestamptz,
  add column if not exists failure_classification text,
  add column if not exists dead_lettered_at timestamptz,
  add column if not exists dead_letter_reason text,
  add column if not exists replay_count integer not null default 0;

alter table action
  add constraint action_retry_count_nonnegative check (retry_count >= 0),
  add constraint action_max_retry_attempts_valid check (max_retry_attempts between 0 and 10),
  add constraint action_replay_count_nonnegative check (replay_count >= 0),
  add constraint action_failure_classification_valid check (
    failure_classification is null or failure_classification in (
      'transient','permanent','drift','authorization','capability','unknown'
    )
  );

create index if not exists idx_action_due_retry
  on action (tenant_id, next_attempt_at, requested_at)
  where status = 'failed' and dead_lettered_at is null and next_attempt_at is not null;

create index if not exists idx_action_dead_letter
  on action (tenant_id, dead_lettered_at desc)
  where dead_lettered_at is not null;

create or replace function classify_action_failure(p_error text)
returns text
language sql
immutable
parallel safe
as $$
  select case
    when coalesce(p_error, '') ~* '^drift:' then 'drift'
    when coalesce(p_error, '') ~* '(401|403|auth|credential|refresh token)' then 'authorization'
    when coalesce(p_error, '') ~* '(unsupported|capability|not implemented)' then 'capability'
    when coalesce(p_error, '') ~* '(429|5[0-9][0-9]|timeout|temporar|rate.?limit|connection)' then 'transient'
    when p_error is null or btrim(p_error) = '' then 'unknown'
    else 'permanent'
  end
$$;

create or replace function schedule_action_failure_retry()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_attempt integer;
  v_delay_seconds integer;
  v_event_type text;
begin
  if new.status <> 'failed' or old.status = 'failed' then
    return new;
  end if;

  v_attempt := old.retry_count + 1;
  new.retry_count := v_attempt;
  new.failure_classification := classify_action_failure(new.error);

  if new.failure_classification = 'transient' and v_attempt <= new.max_retry_attempts then
    v_delay_seconds := least(3600, 60 * (2 ^ greatest(v_attempt - 1, 0))::integer)
      + abs(hashtext(new.id::text || ':' || v_attempt::text)) % 31;
    new.next_attempt_at := now() + make_interval(secs => v_delay_seconds);
    new.dead_lettered_at := null;
    new.dead_letter_reason := null;
    v_event_type := 'action.retry.scheduled';
  else
    new.next_attempt_at := null;
    new.dead_lettered_at := now();
    new.dead_letter_reason := case
      when new.failure_classification = 'transient' then 'retry attempts exhausted'
      else 'failure is not safely retryable'
    end;
    v_event_type := 'action.retry.exhausted';
  end if;

  insert into action_execution_event (
    tenant_id, action_id, actor_type, actor_id, event_type,
    previous_state, new_state, correlation_key, idempotency_key, dedupe_key,
    retry_attempt, entity_type, entity_id, provider_result_classification
  ) values (
    new.tenant_id, new.id, 'system', 'retry-policy', v_event_type,
    old.status, new.status, 'retry-policy:' || new.id::text,
    new.idempotency_key, 'retry:auto:' || v_attempt::text,
    v_attempt, new.entity_type, new.entity_id, new.failure_classification
  ) on conflict (tenant_id, action_id, event_type, dedupe_key) do nothing;

  return new;
end
$$;

drop trigger if exists action_failure_retry_schedule on action;
create trigger action_failure_retry_schedule
before update of status, error on action
for each row execute function schedule_action_failure_retry();

create or replace view v_action_retry_status with (security_invoker = true) as
select id, tenant_id, entity_type, entity_id, action_type, status,
       retry_count, max_retry_attempts, next_attempt_at, last_retry_at,
       failure_classification, dead_lettered_at, dead_letter_reason,
       replay_count, error
from action
where retry_count > 0 or dead_lettered_at is not null;

grant select on v_action_retry_status to axaty_app;
revoke all on function classify_action_failure(text) from public;
grant execute on function classify_action_failure(text) to axaty_app;
