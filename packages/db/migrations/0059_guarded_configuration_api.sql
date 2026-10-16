-- Append-only activation and replay evidence for guarded configuration APIs.
create table configuration_activation_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  entity_type text not null check (entity_type in ('objective','strategy')),
  entity_code text not null check (btrim(entity_code) <> ''),
  version_id uuid not null,
  state text not null check (state in ('active','inactive')),
  actor_user_id uuid not null references auth.auth_user(id) on delete restrict,
  reason text not null check (btrim(reason) <> ''),
  occurred_at timestamptz not null default now()
);
create index configuration_activation_current_idx on configuration_activation_event(tenant_id,entity_type,entity_code,occurred_at desc,id desc);

create table configuration_write_request (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  actor_user_id uuid not null references auth.auth_user(id) on delete restrict,
  idempotency_key text not null check (length(btrim(idempotency_key)) between 8 and 200),
  operation text not null,
  payload_hash text not null check (payload_hash ~ '^[0-9a-f]{64}$'),
  resource_type text not null,
  resource_id uuid not null,
  created_at timestamptz not null default now(),
  unique (tenant_id,actor_user_id,idempotency_key)
);

create trigger configuration_activation_immutable before update or delete on configuration_activation_event for each row execute function protect_configuration_version();
create trigger configuration_request_immutable before update or delete on configuration_write_request for each row execute function protect_configuration_version();
do $$ declare t text; begin foreach t in array array['configuration_activation_event','configuration_write_request'] loop
  execute format('alter table %I enable row level security',t); execute format('alter table %I force row level security',t);
  execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
end loop; end $$;
grant select,insert on configuration_activation_event,configuration_write_request to axaty_app;
