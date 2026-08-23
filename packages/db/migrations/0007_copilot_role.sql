-- 0007_copilot_role.sql
-- A read-only identity for the system copilot (#33, ADR 006).
--
-- Defence in depth, because sql_guard.py is a lexer and not a parser, and
-- anything a model writes is untrusted:
--   1. the role cannot log in on its own and owns nothing
--   2. every transaction it opens is read-only at the server
--   3. select is granted table by table, never "all tables"
--   4. it cannot see marts at all -- only tenant-filtered views over marts
--   5. RLS still applies, because it owns nothing
-- Any one of these failing leaves the other four standing.

-- 1. the role --------------------------------------------------------------

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'axaty_copilot') then
    create role axaty_copilot nologin;
  end if;
end $$;

-- No password here on purpose: a migration lives in git forever, and a password
-- in git is a password that has leaked. Deployment creates the login user:
--   create user axaty_copilot_app with password '<from the vault>';
--   grant axaty_copilot to axaty_copilot_app;
-- and the app connects with DATABASE_URL_COPILOT.

-- 2. server-enforced limits -------------------------------------------------

-- The most important line in this file. If the validator is bypassed entirely
-- -- a parsing trick, a bug, a refactor that forgets to call it -- the write
-- still fails, because the server refuses it.
alter role axaty_copilot set default_transaction_read_only = on;

alter role axaty_copilot set statement_timeout = '15s';
alter role axaty_copilot set idle_in_transaction_session_timeout = '30s';
alter role axaty_copilot set lock_timeout = '2s';

-- 3. what it may read -------------------------------------------------------

revoke all on schema public from axaty_copilot;
grant usage on schema public to axaty_copilot;

-- All RLS-protected, so each grant exposes only the current tenant's rows.
grant select on public.tenant to axaty_copilot;
grant select on public.tenant_settings to axaty_copilot;
grant select on public.rule to axaty_copilot;
grant select on public.rule_evaluation to axaty_copilot;
grant select on public.action to axaty_copilot;
grant select on public.alert to axaty_copilot;
grant select on public.pipeline_run to axaty_copilot;
grant select on public.sku_cost_ledger to axaty_copilot;
grant select on public.ads_profile to axaty_copilot;
grant select on public.sync_watermark to axaty_copilot;
grant select on public.schema_migrations to axaty_copilot;

-- 4. what it must never read ------------------------------------------------

-- Redundant today, since nothing granted these. They exist so that a future
-- "grant select on all tables" written in a hurry cannot quietly hand over
-- encrypted Amazon tokens or user identities.
revoke all on public.amazon_connection from axaty_copilot;
revoke all on public.tenant_member from axaty_copilot;
revoke all on public.tenant_quota from axaty_copilot;
revoke all on public.audit_log from axaty_copilot;
revoke all on public.selling_account from axaty_copilot;

-- The application pins the tenant on the connection before handing it over, so
-- the function must be callable. sql_guard forbids the copilot from calling it
-- in generated SQL.
grant execute on function set_tenant(uuid) to axaty_copilot;

-- 5. marts, through views only ----------------------------------------------

-- marts has no row-level security. That is deliberate: dbt owns those tables
-- and query.py filters tenant_id in every statement it writes. Safe for code
-- that always remembers; not safe for generated SQL.
--
-- So the copilot never touches marts. It reads views that carry the filter
-- themselves. A view runs with its owner's privileges, so the role can read the
-- view while holding no privilege on the table beneath it: the filter cannot be
-- removed by whoever writes the query.

create schema if not exists copilot;
revoke all on schema copilot from public;
grant usage on schema copilot to axaty_copilot;

create or replace function copilot.refresh_views() returns integer as $$
declare
  r record;
  made integer := 0;
begin
  for r in
    select c.table_name
      from information_schema.tables c
     where c.table_schema = 'marts'
       and c.table_type = 'BASE TABLE'
       and exists (
         select 1 from information_schema.columns col
          where col.table_schema = 'marts'
            and col.table_name = c.table_name
            and col.column_name = 'tenant_id'
       )
     order by c.table_name
  loop
    -- drop first: dbt changes mart columns often, and create-or-replace refuses
    -- a changed column list.
    execute format('drop view if exists copilot.%I', r.table_name);
    execute format(
      'create view copilot.%I with (security_barrier = true) as
         select * from marts.%I
          where tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid',
      r.table_name, r.table_name
    );
    execute format('grant select on copilot.%I to axaty_copilot', r.table_name);
    made := made + 1;
  end loop;
  return made;
end $$ language plpgsql;

-- dbt rebuilds mart tables on every run, which takes these dependent views with
-- them. Run this after every build (dbt on-run-end hook):
--   select copilot.refresh_views();
-- It is safe to run when marts is empty: it simply creates nothing.
select copilot.refresh_views();
