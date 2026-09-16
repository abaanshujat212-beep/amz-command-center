-- 0035_notification_preferences.sql
-- Tenant-scoped, false-by-default notification route preferences.

create table notification_route_preference (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  event_type text not null default '*' check (event_type in (
    '*','auth_expiring','auth_expired','pipeline_failed','data_stale',
    'blast_radius_halt','budget_guard','action_failed','economics_incomplete',
    'low_inventory','projected_stockout','reorder_due','inbound_delayed',
    'excess_stock','unusual_demand'
  )),
  channel text not null check (channel in ('in_app','email','whatsapp','sms')),
  enabled boolean not null default false,
  delivery_mode text not null default 'immediate'
    check (delivery_mode in ('immediate','digest')),
  digest_interval_minutes integer,
  timezone text not null default 'UTC' check (btrim(timezone) <> ''),
  quiet_start time without time zone,
  quiet_end time without time zone,
  critical_bypass boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, event_type, channel),
  check ((quiet_start is null) = (quiet_end is null)),
  check (quiet_start is null or quiet_start <> quiet_end),
  check (
    (delivery_mode = 'immediate' and digest_interval_minutes is null) or
    (delivery_mode = 'digest' and digest_interval_minutes in (60, 1440))
  ),
  check (
    channel <> 'in_app' or
    (enabled and delivery_mode = 'immediate' and digest_interval_minutes is null and
     quiet_start is null and quiet_end is null and not critical_bypass)
  )
);

create function validate_notification_preference_timezone()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog, public, pg_temp
as $$
begin
  if not exists (select 1 from pg_timezone_names where name = new.timezone) then
    raise exception 'invalid notification timezone: %', new.timezone
      using errcode = '22023';
  end if;
  return new;
end
$$;

create trigger notification_preference_timezone_valid
before insert or update of timezone on notification_route_preference
for each row execute function validate_notification_preference_timezone();

create index idx_notification_preference_tenant_channel
  on notification_route_preference (tenant_id, channel, event_type);

alter table notification_route_preference enable row level security;
alter table notification_route_preference force row level security;
create policy tenant_isolation on notification_route_preference
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

revoke all on notification_route_preference from axaty_app;
grant select, insert, update, delete on notification_route_preference to axaty_app;
