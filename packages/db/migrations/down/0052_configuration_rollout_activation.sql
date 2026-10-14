create or replace function validate_configuration_rollout_event() returns trigger
language plpgsql security invoker set search_path=public,pg_temp as $$
declare latest text;
begin
  perform pg_advisory_xact_lock(hashtextextended(new.tenant_id::text||':'||new.simulation_id::text,0));
  select state into latest from configuration_rollout_event
   where tenant_id=new.tenant_id and simulation_id=new.simulation_id
   order by occurred_at desc,id desc limit 1;
  if latest is null and new.state<>'CANARY' then raise exception 'rollout must start with CANARY'; end if;
  if latest in('ROLLED_BACK','COMPLETED') then raise exception 'terminal rollout cannot transition'; end if;
  if new.state='EXPANDED' and latest not in('CANARY','EXPANDED') then raise exception 'invalid rollout expansion'; end if;
  return new;
end $$;

alter table configuration_rollout_event
  drop column completion_metadata,
  drop column prior_override_id,
  drop column applied_override_id;
