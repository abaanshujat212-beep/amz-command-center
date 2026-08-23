-- down/0007_copilot_role.sql
--
-- cascade removes refresh_views() and every copilot.* view. It cannot touch the
-- marts tables underneath, which are owned by dbt.
drop schema if exists copilot cascade;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'axaty_copilot') then
    -- Grants must go before the role can be dropped. drop owned by removes the
    -- privileges this role holds in this database, not the objects themselves,
    -- because the role owns nothing.
    execute 'drop owned by axaty_copilot';
    execute 'drop role axaty_copilot';
  end if;
end $$;
