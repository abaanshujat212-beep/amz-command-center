-- Durable external dependency readiness and separately managed module visibility.
create table external_dependency_state (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  marketplace_id text not null default 'A1F83G8C2ARO7P',
  module_key text not null,
  dependency_key text not null,
  readiness_state text not null default 'NOT_CONFIGURED' check (readiness_state in (
    'NOT_CONFIGURED','WAITING_FOR_API_APPROVAL','WAITING_FOR_AUTHORIZATION',
    'WAITING_FOR_MARKETING_STREAM','WAITING_FOR_AMC','UNSUPPORTED_MARKETPLACE',
    'UNSUPPORTED_API_VERSION','LIVE_READY')),
  reason_code text,
  evidence_source text,
  evidence_observed_at timestamptz,
  evidence_expires_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, marketplace_id, module_key, dependency_key),
  check (readiness_state <> 'LIVE_READY' or (evidence_source is not null and evidence_observed_at is not null)),
  check (evidence_expires_at is null or evidence_observed_at is null or evidence_expires_at > evidence_observed_at)
);

create table module_state (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  marketplace_id text not null default 'A1F83G8C2ARO7P',
  module_key text not null,
  entitlement_state text not null default 'NOT_ENTITLED' check (entitlement_state in ('NOT_ENTITLED','ENTITLED')),
  visibility_state text not null default 'DISABLED' check (visibility_state in (
    'DISABLED','RECOMMENDED','ENABLED','BETA','EXTERNAL_ACCESS_REQUIRED','NOT_READY')),
  reason_code text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, marketplace_id, module_key)
);

create index idx_external_dependency_state_tenant_module on external_dependency_state (tenant_id, module_key, readiness_state);
create index idx_module_state_tenant_visibility on module_state (tenant_id, visibility_state);

alter table external_dependency_state enable row level security;
alter table external_dependency_state force row level security;
create policy tenant_isolation on external_dependency_state
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
alter table module_state enable row level security;
alter table module_state force row level security;
create policy tenant_isolation on module_state
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

grant select, insert, update, delete on external_dependency_state, module_state to axaty_app;

create or replace function audit_readiness_transition() returns trigger language plpgsql as $$
begin
  insert into audit_log (tenant_id, action, entity, before, after)
  values (new.tenant_id, 'readiness.transition', tg_table_name || ':' || new.id::text,
          case when tg_op = 'UPDATE' then to_jsonb(old) else null end, to_jsonb(new));
  return new;
end $$;
create trigger external_dependency_state_audit after insert or update on external_dependency_state
  for each row execute function audit_readiness_transition();
create trigger module_state_audit after insert or update on module_state
  for each row execute function audit_readiness_transition();
