create table if not exists tenant_role_template (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  name text not null,
  description text,
  scopes text[] not null default array['reporting'],
  created_at timestamptz not null default now(),
  unique (tenant_id, name),
  check (array_length(scopes, 1) > 0)
);

alter table tenant_member add column if not exists access_scopes text[] not null default array['reporting'];
alter table tenant_role_template enable row level security;
alter table tenant_role_template force row level security;
drop policy if exists tenant_isolation on tenant_role_template;
create policy tenant_isolation on tenant_role_template
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
grant select, insert, update, delete on tenant_role_template to axaty_app;
