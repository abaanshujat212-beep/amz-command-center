-- 0008_app_reads_marts_through_views.sql
--
-- 0007 gave the copilot tenant-filtered views over marts, because marts has no
-- row-level security and generated SQL cannot be trusted to filter by hand.
--
-- The dashboard has the same problem. apps/web/lib/db.ts reads mart tables to
-- render the PPC Command Center, and a single query that forgets its tenant
-- filter would show one client another client's spend. A careful developer is
-- not a security control.
--
-- Note what axaty_app was granted in 0002: select/insert/update/delete on all
-- tables in schema *public*. Nothing in marts. So the application role cannot
-- read a mart table directly at all -- it can only reach the filtered views.
-- The unsafe path is not merely discouraged; it does not exist for that role.
--
-- The only reason the dashboard could read marts at all was that db.ts was
-- connecting with DATABASE_URL, the owner role, instead of DATABASE_URL_APP.
-- That is fixed in the same change as this migration.

grant usage on schema copilot to axaty_app;

-- Belt and braces: make the direct path explicitly closed, so that a future
-- "grant everything in marts" cannot quietly reopen it.
revoke all on schema marts from axaty_app;

-- Same function as 0007, now granting both readers. The schema keeps its name
-- for continuity: it was built for the copilot and the dashboard joined it.
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
    execute format('grant select on copilot.%I to axaty_app', r.table_name);
    made := made + 1;
  end loop;
  return made;
end $$ language plpgsql;

select copilot.refresh_views();
