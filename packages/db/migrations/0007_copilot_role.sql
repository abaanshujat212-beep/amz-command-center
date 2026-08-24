-- 0007_copilot_role.sql
-- A read-only identity for the system copilot (#33, ADR 006).

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'axaty_copilot') then
    create role axaty_copilot nologin;
  end if;
end $$;

-- No password here on purpose. Deployment creates the login user and grants
-- axaty_copilot to that login.

alter role axaty_copilot set default_transaction_read_only = on;
alter role axaty_copilot set statement_timeout = '15s';
alter role axaty_copilot set idle_in_transaction_session_timeout = '30s';
alter role axaty_copilot set lock_timeout = '2s';

revoke all on schema public from axaty_copilot;
grant usage on schema public to axaty_copilot;

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

-- Redundant today, since nothing granted these. They exist so a future broad
-- permission shortcut cannot quietly hand over encrypted Amazon tokens or user
-- identities.
revoke all on public.amazon_connection from axaty_copilot;
revoke all on public.tenant_member from axaty_copilot;
revoke all on public.tenant_quota from axaty_copilot;
revoke all on public.audit_log from axaty_copilot;
revoke all on public.selling_account from axaty_copilot;

grant execute on function set_tenant(uuid) to axaty_copilot;

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

select copilot.refresh_views();
