-- 0002_rls.sql
-- Row Level Security. The database, not the application, is the boundary.
--
-- Requirements:
--   * the application role must NOT own these tables and must NOT be superuser
--   * FORCE ROW LEVEL SECURITY so even the owner is subject to policies
--   * every request runs: SET LOCAL app.tenant_id = '<uuid>'
--   * with no tenant context set, queries return zero rows (fail closed)

do $$
declare
  t text;
  tenant_tables text[] := array[
    'tenant_member',
    'tenant_settings',
    'tenant_quota',
    'amazon_connection',
    'ads_profile',
    'selling_account',
    'sync_watermark',
    'pipeline_run',
    'audit_log'
  ];
begin
  foreach t in array tenant_tables loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force  row level security', t);

    execute format('drop policy if exists tenant_isolation on %I', t);
    execute format($f$
      create policy tenant_isolation on %I
        using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    $f$, t);
  end loop;
end $$;

-- The tenant table itself: a session may only see its own tenant row.
alter table tenant enable row level security;
alter table tenant force  row level security;
drop policy if exists tenant_self on tenant;
create policy tenant_self on tenant
  using (id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (id = nullif(current_setting('app.tenant_id', true), '')::uuid);

-- Application role (least privilege). Password comes from the environment in
-- real deployments; this default exists only for local development.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'axaty_app') then
    create role axaty_app login password 'axaty_app';
  end if;
end $$;

grant usage on schema public to axaty_app;
grant select, insert, update, delete on all tables in schema public to axaty_app;
alter default privileges in schema public
  grant select, insert, update, delete on tables to axaty_app;

-- Helper used by the application layer on every transaction.
create or replace function set_tenant(p_tenant uuid) returns void as $$
begin
  perform set_config('app.tenant_id', p_tenant::text, true);  -- true = transaction-local
end $$ language plpgsql;
