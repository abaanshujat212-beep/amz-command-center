-- Bind completed rollouts to immutable configuration versions and retain rollback lineage.
alter table configuration_rollout_event
  add column applied_override_id uuid,
  add column prior_override_id uuid,
  add column completion_metadata jsonb not null default '{}'::jsonb
    check (jsonb_typeof(completion_metadata)='object'),
  add foreign key(applied_override_id,tenant_id)
    references configuration_override_version(id,tenant_id) on delete restrict,
  add foreign key(prior_override_id,tenant_id)
    references configuration_override_version(id,tenant_id) on delete restrict;

create or replace function validate_configuration_rollout_event() returns trigger
language plpgsql security invoker set search_path=public,pg_temp as $$
declare latest_state text; latest_exposure numeric(5,2);
begin
  perform pg_advisory_xact_lock(hashtextextended(new.tenant_id::text||':'||new.simulation_id::text,0));
  select state,exposure_pct into latest_state,latest_exposure
    from configuration_rollout_event
   where tenant_id=new.tenant_id and simulation_id=new.simulation_id
   order by occurred_at desc,id desc limit 1;
  if latest_state is null and new.state<>'CANARY' then
    raise exception 'rollout must start with CANARY';
  end if;
  if latest_state is not null and new.state='CANARY' then
    raise exception 'rollout can only enter CANARY once';
  end if;
  if latest_state='ROLLED_BACK' then
    raise exception 'terminal rollout cannot transition';
  end if;
  if latest_state='COMPLETED' and new.state<>'ROLLED_BACK' then
    raise exception 'completed rollout can only be rolled back';
  end if;
  if new.state='EXPANDED' and latest_state not in('CANARY','EXPANDED') then
    raise exception 'invalid rollout expansion';
  end if;
  if new.state='EXPANDED' and new.exposure_pct<=latest_exposure then
    raise exception 'rollout exposure must increase';
  end if;
  if new.state in('CANARY','EXPANDED') and new.exposure_pct>=100 then
    raise exception '100 percent exposure must be recorded as COMPLETED';
  end if;
  if new.state='COMPLETED' and (
       latest_state not in('CANARY','EXPANDED') or new.exposure_pct<>100
       or new.applied_override_id is null or new.completion_metadata='{}'::jsonb) then
    raise exception 'completed rollout requires 100 percent exposure and activation metadata';
  end if;
  if new.state='ROLLED_BACK' and latest_state='COMPLETED'
     and new.applied_override_id is null then
    raise exception 'completed rollout rollback requires a restoring configuration version';
  end if;
  return new;
end $$;

