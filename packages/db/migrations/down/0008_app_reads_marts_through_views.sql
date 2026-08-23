-- down/0008_app_reads_marts_through_views.sql
--
-- Take the dashboard's access away again. The views themselves belong to 0007,
-- so they stay; only axaty_app's ability to reach them is removed.

do $$
declare
  r record;
begin
  for r in
    select table_name from information_schema.views where table_schema = 'copilot'
  loop
    execute format('revoke all on copilot.%I from axaty_app', r.table_name);
  end loop;
end $$;

revoke usage on schema copilot from axaty_app;
