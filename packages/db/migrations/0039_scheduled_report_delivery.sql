-- 0039_scheduled_report_delivery.sql
-- Governed schedules for report jobs. Delivery still flows through the canonical
-- notification router; this migration creates no provider adapter or secret store.

alter table alert drop constraint alert_kind_check;
alter table alert add constraint alert_kind_check check (kind in (
  'auth_expiring','auth_expired','pipeline_failed','data_stale',
  'blast_radius_halt','budget_guard','action_failed','economics_incomplete',
  'low_inventory','projected_stockout','reorder_due','inbound_delayed',
  'excess_stock','unusual_demand','report_ready'
));

alter table notification_event drop constraint notification_event_event_type_check;
alter table notification_event add constraint notification_event_event_type_check check (event_type in (
  'auth_expiring','auth_expired','pipeline_failed','data_stale',
  'blast_radius_halt','budget_guard','action_failed','economics_incomplete',
  'low_inventory','projected_stockout','reorder_due','inbound_delayed',
  'excess_stock','unusual_demand','report_ready'
));
alter table notification_event drop constraint notification_event_source_check;
alter table notification_event add constraint notification_event_source_check check (source in (
  'scheduler','action_worker','inventory_engine','internal','report_worker'
));

-- Keep the alert bridge and its table constraint in lockstep. The bridge remains
-- the only path that creates notification events and channel delivery records.
create or replace function route_alert_to_notification()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_event_id uuid;
  v_source text;
  v_source_ref text;
  v_dedupe_key text;
begin
  if new.detail ? 'notification_source' then
    v_source := new.detail->>'notification_source';
    if v_source not in (
      'scheduler','action_worker','inventory_engine','internal','report_worker'
    ) then
      raise exception 'unsupported notification source: %', v_source;
    end if;
  elsif new.detail ? 'scheduler_kind' then
    v_source := 'scheduler';
  elsif new.detail ? 'action_id' or new.detail->>'provider' = 'ads_api' then
    v_source := 'action_worker';
  else
    v_source := 'internal';
  end if;

  v_source_ref := coalesce(
    nullif(new.detail->>'notification_source_ref', ''),
    nullif(new.entity_ref, ''),
    new.id::text
  );
  v_dedupe_key := coalesce(nullif(new.dedupe_key, ''), new.id::text);

  insert into notification_event (
    tenant_id,event_type,source,source_ref,dedupe_key,severity,title,payload,occurred_at
  ) values (
    new.tenant_id,new.kind,v_source,v_source_ref,v_dedupe_key,new.severity,new.title,
    coalesce(new.detail->'event_payload',new.detail,'{}'::jsonb),new.created_at
  )
  on conflict (tenant_id,source,dedupe_key) do nothing
  returning id into v_event_id;

  if v_event_id is null then
    select id into v_event_id from notification_event
     where tenant_id = new.tenant_id and source = v_source and dedupe_key = v_dedupe_key;
  end if;

  update alert set notification_event_id = v_event_id where id = new.id;

  insert into notification_delivery (
    tenant_id,event_id,channel,status,attempt,retry_eligible,alert_id,
    cost_amount,delivered_at
  ) values (
    new.tenant_id,v_event_id,'in_app','DELIVERED',1,false,new.id,0,new.created_at
  ) on conflict (tenant_id,event_id,channel) do nothing;

  insert into notification_delivery (
    tenant_id,event_id,channel,status,attempt,retry_eligible,error,cost_amount
  )
  select new.tenant_id,v_event_id,channel,'BLOCKED_CONFIGURATION',0,false,
         'channel is not configured',0
    from unnest(array['email','whatsapp','sms']::text[]) as channel
  on conflict (tenant_id,event_id,channel) do nothing;

  return new;
end
$$;

alter table notification_route_preference drop constraint notification_route_preference_event_type_check;
alter table notification_route_preference add constraint notification_route_preference_event_type_check check (event_type in (
  '*','auth_expiring','auth_expired','pipeline_failed','data_stale',
  'blast_radius_halt','budget_guard','action_failed','economics_incomplete',
  'low_inventory','projected_stockout','reorder_due','inbound_delayed',
  'excess_stock','unusual_demand','report_ready'
));

alter table notification_consent_event drop constraint notification_consent_event_purpose_check;
alter table notification_consent_event add constraint notification_consent_event_purpose_check
  check (purpose in ('operational_alert','report_delivery'));

create table report_delivery_schedule (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  report_definition_id uuid not null,
  name text not null check (btrim(name) <> ''),
  cadence text not null check (cadence in ('daily','weekly','monthly')),
  run_time time without time zone not null,
  weekday smallint check (weekday between 0 and 6),
  month_day smallint check (month_day between 1 and 28),
  timezone text not null check (btrim(timezone) <> ''),
  recipient_user_id uuid not null references auth.auth_user(id) on delete restrict,
  channels text[] not null default '{in_app}',
  date_window_days integer not null default 30 check (date_window_days between 1 and 366),
  output_format text not null check (output_format in ('csv','xlsx','pdf')),
  filters jsonb not null default '{}'::jsonb check (jsonb_typeof(filters) = 'object'),
  enabled boolean not null default true,
  next_run_at timestamptz not null,
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (report_definition_id, tenant_id)
    references report_definition(id, tenant_id) on delete restrict,
  unique (id, tenant_id),
  check (cardinality(channels) > 0 and channels <@ array['in_app','email','whatsapp','sms']::text[]),
  check ((cadence = 'weekly') = (weekday is not null)),
  check ((cadence = 'monthly') = (month_day is not null))
);

create table report_delivery_run (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  schedule_id uuid not null,
  report_job_id uuid,
  notification_event_id uuid,
  scheduled_for timestamptz not null,
  status text not null check (status in (
    'queued','artifact_pending','routed','blocked_recipient','blocked_expired','failed'
  )),
  reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (schedule_id, tenant_id)
    references report_delivery_schedule(id, tenant_id) on delete restrict,
  foreign key (report_job_id, tenant_id)
    references report_job(id, tenant_id) on delete restrict,
  foreign key (notification_event_id, tenant_id)
    references notification_event(id, tenant_id) on delete restrict,
  unique (tenant_id, schedule_id, scheduled_for),
  unique (id, tenant_id)
);

create index idx_report_delivery_schedule_due
  on report_delivery_schedule (tenant_id, next_run_at) where enabled;
create index idx_report_delivery_run_job
  on report_delivery_run (tenant_id, report_job_id, status);

create function validate_report_schedule_timezone() returns trigger
language plpgsql security invoker set search_path = pg_catalog, public, pg_temp as $$
begin
  if not exists (select 1 from pg_timezone_names where name = new.timezone) then
    raise exception 'invalid report schedule timezone: %', new.timezone using errcode = '22023';
  end if;
  return new;
end
$$;
create trigger report_schedule_timezone_valid
before insert or update of timezone on report_delivery_schedule
for each row execute function validate_report_schedule_timezone();

alter table report_delivery_schedule enable row level security;
alter table report_delivery_schedule force row level security;
create policy tenant_isolation on report_delivery_schedule
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
alter table report_delivery_run enable row level security;
alter table report_delivery_run force row level security;
create policy tenant_isolation on report_delivery_run
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

revoke all on report_delivery_schedule, report_delivery_run from axaty_app;
grant select, insert, update, delete on report_delivery_schedule to axaty_app;
grant select, insert, update on report_delivery_run to axaty_app;
