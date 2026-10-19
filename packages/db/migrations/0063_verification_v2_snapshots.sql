-- Multi-horizon, read-only verification evidence. Existing action T+7 fields
-- remain the compatibility summary; this table is the reproducible ledger.
create table action_verification_snapshot (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  action_id uuid not null,
  horizon_days integer not null check (horizon_days in (1,3,7,14,30)),
  status text not null check (status in ('COMPLETE','INSUFFICIENT_DATA','FAILED')),
  outcome text check (outcome in ('improved','worsened','neutral','inconclusive')),
  metric_keys jsonb not null check (jsonb_typeof(metric_keys)='array'),
  baseline_metrics jsonb not null check (jsonb_typeof(baseline_metrics)='object'),
  observed_metrics jsonb not null check (jsonb_typeof(observed_metrics)='object'),
  window_before_start date not null,
  window_before_end date not null,
  window_after_start date not null,
  window_after_end date not null,
  data_through date,
  reason_code text,
  checked_at timestamptz not null default now(),
  completed_at timestamptz,
  unique(id,tenant_id),
  unique(tenant_id,action_id,horizon_days),
  foreign key(action_id,tenant_id) references action(id,tenant_id) on delete cascade,
  check ((status='COMPLETE' and outcome is not null and completed_at is not null and reason_code is null)
      or (status<>'COMPLETE' and outcome is null and completed_at is null and reason_code is not null))
);

create index action_verification_snapshot_read_idx
  on action_verification_snapshot(tenant_id,action_id,horizon_days);

create function protect_complete_verification_snapshot() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$ begin
  if old.status='COMPLETE' then raise exception 'completed verification snapshots are immutable'; end if;
  if new.tenant_id<>old.tenant_id or new.action_id<>old.action_id or new.horizon_days<>old.horizon_days then
    raise exception 'verification snapshot identity is immutable';
  end if;
  return new;
end $$;
create trigger action_verification_snapshot_complete_immutable before update on action_verification_snapshot
for each row execute function protect_complete_verification_snapshot();

alter table action_verification_snapshot enable row level security;
alter table action_verification_snapshot force row level security;
create policy tenant_isolation on action_verification_snapshot
  using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
  with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
grant select,insert,update on action_verification_snapshot to axaty_app;
