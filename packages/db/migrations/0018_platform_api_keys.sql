create table if not exists tenant_api_key (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  name text not null,
  key_prefix text not null,
  key_hash text not null unique,
  scopes text[] not null default array['read'],
  created_by uuid,
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at timestamptz,
  check (array_length(scopes, 1) > 0)
);
create index if not exists idx_tenant_api_key_tenant_active on tenant_api_key(tenant_id, created_at desc) where revoked_at is null;
alter table tenant_api_key enable row level security;
alter table tenant_api_key force row level security;
drop policy if exists tenant_isolation on tenant_api_key;
create policy tenant_isolation on tenant_api_key
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
grant select, insert, update, delete on tenant_api_key to axaty_app;
