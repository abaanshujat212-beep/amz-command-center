-- 0037_notification_consent_ledger.sql
-- Immutable tenant-scoped consent history. Contact data is never consent.

create table notification_consent_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  recipient_ref text not null check (btrim(recipient_ref) <> ''),
  channel text not null check (channel in ('email','whatsapp','sms')),
  purpose text not null check (purpose in ('operational_alert')),
  decision text not null check (decision in ('granted','revoked')),
  actor_user_id uuid,
  reason text,
  occurred_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (id, tenant_id)
);

create index idx_notification_consent_effective
  on notification_consent_event (tenant_id, recipient_ref, channel, purpose, occurred_at desc, created_at desc);

create function protect_notification_consent_event()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  raise exception 'notification consent history is immutable';
end
$$;

create trigger notification_consent_event_immutable
before update or delete on notification_consent_event
for each row execute function protect_notification_consent_event();

create function notification_consent_effective(
  p_tenant_id uuid,
  p_recipient_ref text,
  p_channel text,
  p_purpose text
)
returns boolean
language sql
stable
security invoker
set search_path = public, pg_temp
as $$
  select coalesce((
    select decision = 'granted'
      from notification_consent_event
     where tenant_id = p_tenant_id
       and recipient_ref = p_recipient_ref
       and channel = p_channel
       and purpose = p_purpose
     order by occurred_at desc, created_at desc, id desc
     limit 1
  ), false)
$$;

alter table notification_consent_event enable row level security;
alter table notification_consent_event force row level security;
create policy tenant_isolation on notification_consent_event
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

revoke all on notification_consent_event from axaty_app;
grant select, insert on notification_consent_event to axaty_app;
grant execute on function notification_consent_effective(uuid, text, text, text) to axaty_app;
