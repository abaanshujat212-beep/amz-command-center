-- Down for 0007_copilot_role.sql
--
-- Order matters: the views and grants have to go before the role can be
-- dropped, otherwise Postgres refuses with "role cannot be dropped because some
-- objects depend on it".

drop schema if exists copilot cascade;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'axaty_copilot') then
    -- clears every grant made to the role across the database
    execute 'drop owned by axaty_copilot';
    execute 'drop role axaty_copilot';
  end if;
end $$;
