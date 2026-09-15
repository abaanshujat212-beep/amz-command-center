-- 0034_notification_router_core.sql
-- Canonical tenant-scoped internal events routed into the existing alert inbox.

alter table alert drop constraint if exists alert_kind_check;
alter table alert add constraint alert_kind_check check (kind in (
  'auth_expiring','auth_expired','pipeline_failed','data_stale',
  'blast_radius_halt','budget_guard','action_failed','economics_incomplete',
  'low_inventory','projected_stockout','reorder_due','inbound_delayed',
  'excess_stock','unusual_demand'
));

alter table alert
  add column dedupe_key text,
  add column notification_event_id uuid,
  add constraint alert_dedupe_key_nonempty
    check (dedupe_key is null or btrim(dedupe_key) <> ''),
  add constraint uq_alert_id_tenant unique (id, tenant_id);

create unique index uq_alert_tenant_dedupe
  on alert (tenant_id, dedupe_key)
  where dedupe_key is not null;

create table notification_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  event_type text not null check (event_type in (
    'auth_expiring','auth_expired','pipeline_failed','data_stale',
    'blast_radius_halt','budget_guard','action_failed','economics_incomplete',
    'low_inventory','projected_stockout','reorder_due','inbound_delayed',
    'excess_stock','unusual_demand'
  )),
  source text not null check (source in (
    'scheduler','action_worker','inventory_engine','internal'
  )),
  source_ref text not null check (btrim(source_ref) <> ''),
  dedupe_key text not null check (btrim(dedupe_key) <> ''),
  severity text not null check (severity in ('info','warning','critical')),
  title text not null check (btrim(title) <> ''),
  payload jsonb not null default '{}'::jsonb
    check (jsonb_typeof(payload) = 'object'),
  occurred_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, source, dedupe_key)
);

alter table alert add constraint fk_alert_notification_event_tenant
  foreign key (notification_event_id, tenant_id)
  references notification_event(id, tenant_id) on delete restrict;

create table notification_delivery (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  event_id uuid not null,
  channel text not null check (channel in ('in_app','email','whatsapp','sms')),
  status text not null check (status in (
    'PENDING','DELIVERED','FAILED','RETRYABLE','DEAD_LETTER','BLOCKED_CONFIGURATION'
  )),
  attempt integer not null default 0 check (attempt >= 0),
  retry_eligible boolean not null default false,
  alert_id uuid,
  provider_reference text,
  error text,
  cost_amount numeric(14,6) not null default 0 check (cost_amount >= 0),
  cost_currency text,
  delivered_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (event_id, tenant_id)
    references notification_event(id, tenant_id) on delete cascade,
  foreign key (alert_id, tenant_id)
    references alert(id, tenant_id) on delete restrict,
  unique (tenant_id, event_id, channel),
  check (cost_amount = 0 or btrim(cost_currency) <> ''),
  check (channel <> 'in_app' or status <> 'DELIVERED' or
         (alert_id is not null and delivered_at is not null and cost_amount = 0))
);

create index idx_notification_event_tenant_occurred
  on notification_event (tenant_id, occurred_at desc);
create index idx_notification_delivery_tenant_status
  on notification_delivery (tenant_id, status, created_at desc);

create function protect_notification_event()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  raise exception 'notification event is immutable';
end
$$;

create trigger notification_event_immutable
before update on notification_event
for each row execute function protect_notification_event();

create function route_alert_to_notification()
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
    if v_source not in ('scheduler','action_worker','inventory_engine','internal') then
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

create trigger alert_notification_route
after insert on alert
for each row execute function route_alert_to_notification();

alter table notification_event enable row level security;
alter table notification_event force row level security;
create policy tenant_isolation on notification_event
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

alter table notification_delivery enable row level security;
alter table notification_delivery force row level security;
create policy tenant_isolation on notification_delivery
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

revoke all on notification_event, notification_delivery from axaty_app;
grant select, insert on notification_event to axaty_app;
grant select, insert, update on notification_delivery to axaty_app;
