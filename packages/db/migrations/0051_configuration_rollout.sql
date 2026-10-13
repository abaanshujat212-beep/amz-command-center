-- Immutable no-write simulations and stateful-but-append-only rollout events.
create table configuration_simulation (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  scope_type text not null check(scope_type in('tenant','marketplace','entity')), scope_id text not null,
  proposed_values jsonb not null check(jsonb_typeof(proposed_values)='object'), input_fingerprint text not null,
  entity_count integer not null, affected_count integer not null, protected_excluded integer not null,
  estimated_spend numeric(14,2) not null, estimated_spend_delta numeric(14,2) not null,
  risk_score numeric(8,4) not null, exposure_limit integer not null, result jsonb not null,
  created_by uuid not null references auth.auth_user(id), created_at timestamptz not null default now(),
  unique(id,tenant_id), unique(tenant_id,input_fingerprint),
  check(affected_count>=0 and protected_excluded>=0 and affected_count<=entity_count),
  check(exposure_limit>=0 and affected_count<=exposure_limit)
);
create table configuration_rollout_event (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  simulation_id uuid not null, state text not null check(state in('CANARY','EXPANDED','ROLLED_BACK','COMPLETED')),
  exposure_pct numeric(5,2) not null check(exposure_pct>=0 and exposure_pct<=100), entity_ids jsonb not null,
  reason text not null check(btrim(reason)<>''), actor_user_id uuid not null references auth.auth_user(id),
  occurred_at timestamptz not null default clock_timestamp(),
  foreign key(simulation_id,tenant_id) references configuration_simulation(id,tenant_id)
);
create function validate_configuration_rollout_event() returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
declare latest text; begin
 perform pg_advisory_xact_lock(hashtextextended(new.tenant_id::text||':'||new.simulation_id::text,0));
 select state into latest from configuration_rollout_event where tenant_id=new.tenant_id and simulation_id=new.simulation_id order by occurred_at desc,id desc limit 1;
 if latest is null and new.state<>'CANARY' then raise exception 'rollout must start with CANARY'; end if;
 if latest in('ROLLED_BACK','COMPLETED') then raise exception 'terminal rollout cannot transition'; end if;
 if new.state='EXPANDED' and latest not in('CANARY','EXPANDED') then raise exception 'invalid rollout expansion'; end if;
 return new;
end $$;
create trigger configuration_rollout_event_valid before insert on configuration_rollout_event for each row execute function validate_configuration_rollout_event();
create trigger configuration_simulation_immutable before update on configuration_simulation for each row execute function protect_configuration_version();
create trigger configuration_rollout_event_immutable before update on configuration_rollout_event for each row execute function protect_configuration_version();
do $$ declare t text; begin foreach t in array array['configuration_simulation','configuration_rollout_event'] loop
 execute format('alter table %I enable row level security',t); execute format('alter table %I force row level security',t);
 execute format('create policy tenant_isolation on %I using(tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check(tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
end loop; end $$;
grant select,insert on configuration_simulation,configuration_rollout_event to axaty_app;
