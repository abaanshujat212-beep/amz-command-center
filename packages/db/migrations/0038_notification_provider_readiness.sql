-- 0038_notification_provider_readiness.sql
-- Explicit, auditable provider readiness. Credential/config presence never implies READY.

create table notification_provider_state (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  channel text not null check (channel in ('email','whatsapp','sms')),
  readiness_state text not null default 'BLOCKED_CONFIGURATION' check (readiness_state in (
    'BLOCKED_CONFIGURATION','PENDING_REVIEW','VERIFICATION_REQUIRED','READY','SUSPENDED','EXPIRED'
  )),
  config_ref text,
  credential_ref text,
  verification_ref text,
  readiness_reason text,
  evidence_observed_at timestamptz,
  evidence_expires_at timestamptz,
  actor_user_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, channel),
  check (readiness_state <> 'READY' or (verification_ref is not null and evidence_observed_at is not null)),
  check (evidence_expires_at is null or evidence_observed_at is null or evidence_expires_at > evidence_observed_at),
  check (config_ref is null or length(config_ref) <= 512),
  check (credential_ref is null or length(credential_ref) <= 512),
  check (verification_ref is null or length(verification_ref) <= 512)
);

create table notification_provider_state_audit (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  provider_state_id uuid not null,
  channel text not null check (channel in ('email','whatsapp','sms')),
  readiness_state text not null check (readiness_state in (
    'BLOCKED_CONFIGURATION','PENDING_REVIEW','VERIFICATION_REQUIRED','READY','SUSPENDED','EXPIRED'
  )),
  config_ref text,
  credential_ref text,
  verification_ref text,
  readiness_reason text,
  actor_user_id uuid,
  recorded_at timestamptz not null default now(),
  foreign key (provider_state_id, tenant_id) references notification_provider_state(id, tenant_id) on delete restrict
);

create index idx_notification_provider_state_tenant_channel on notification_provider_state (tenant_id, channel, readiness_state);
create index idx_notification_provider_audit_tenant_time on notification_provider_state_audit (tenant_id, recorded_at desc);

create function audit_notification_provider_state() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  insert into notification_provider_state_audit (
    tenant_id, provider_state_id, channel, readiness_state, config_ref,
    credential_ref, verification_ref, readiness_reason, actor_user_id
  ) values (
    new.tenant_id, new.id, new.channel, new.readiness_state, new.config_ref,
    new.credential_ref, new.verification_ref, new.readiness_reason, new.actor_user_id
  );
  return new;
end
$$;

create function protect_notification_provider_audit() returns trigger
language plpgsql security invoker set search_path = public, pg_temp as $$
begin
  raise exception 'notification provider audit is immutable';
end
$$;

create trigger notification_provider_state_audit
after insert or update on notification_provider_state
for each row execute function audit_notification_provider_state();

create trigger notification_provider_state_audit_immutable
before update on notification_provider_state_audit
for each row execute function protect_notification_provider_audit();

alter table notification_provider_state enable row level security;
alter table notification_provider_state force row level security;
create policy tenant_isolation on notification_provider_state
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

alter table notification_provider_state_audit enable row level security;
alter table notification_provider_state_audit force row level security;
create policy tenant_isolation on notification_provider_state_audit
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

revoke all on notification_provider_state, notification_provider_state_audit from axaty_app;
grant select, insert, update on notification_provider_state to axaty_app;
grant select on notification_provider_state_audit to axaty_app;
