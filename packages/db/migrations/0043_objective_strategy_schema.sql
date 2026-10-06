-- 0043_objective_strategy_schema.sql
-- Versioned objective/strategy configuration. Templates are disabled by default.

create table objective_version (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  code text not null check (btrim(code) <> ''),
  version integer not null check (version > 0),
  mode text not null check (mode in ('profitability','growth','efficiency','launch','defend')),
  name text not null check (btrim(name) <> ''),
  enabled boolean not null default false,
  targets jsonb not null default '{}'::jsonb check (jsonb_typeof(targets)='object'),
  guardrails jsonb not null default '{}'::jsonb check (jsonb_typeof(guardrails)='object'),
  created_by uuid references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (id,tenant_id),
  unique (tenant_id,code,version),
  check (not enabled or targets <> '{}'::jsonb)
);

create table strategy_version (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  objective_version_id uuid not null,
  code text not null check (btrim(code) <> ''),
  version integer not null check (version > 0),
  mode text not null check (mode in ('conservative','balanced','growth','harvest','launch')),
  name text not null check (btrim(name) <> ''),
  enabled boolean not null default false,
  settings jsonb not null default '{}'::jsonb check (jsonb_typeof(settings)='object'),
  guardrails jsonb not null default '{}'::jsonb check (jsonb_typeof(guardrails)='object'),
  created_by uuid references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (id,tenant_id),
  unique (tenant_id,code,version),
  foreign key (objective_version_id,tenant_id) references objective_version(id,tenant_id) on delete restrict,
  check (not enabled or settings <> '{}'::jsonb)
);

create table configuration_run_binding (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  run_type text not null check (run_type in ('rules','optimizer','simulation')),
  run_ref text not null check (btrim(run_ref) <> ''),
  objective_version_id uuid not null,
  strategy_version_id uuid not null,
  bound_at timestamptz not null default now(),
  unique (tenant_id,run_type,run_ref),
  foreign key (objective_version_id,tenant_id) references objective_version(id,tenant_id) on delete restrict,
  foreign key (strategy_version_id,tenant_id) references strategy_version(id,tenant_id) on delete restrict
);

create table configuration_version_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  entity_type text not null check (entity_type in ('objective','strategy')),
  entity_id uuid not null,
  event_type text not null check (event_type in ('created','enabled','disabled','superseded')),
  actor_user_id uuid references auth.auth_user(id) on delete restrict,
  reason text not null check (btrim(reason) <> ''),
  occurred_at timestamptz not null default now()
);

create function validate_configuration_guardrails(payload jsonb) returns boolean
language sql immutable strict as $$
  select jsonb_typeof(payload)='object'
    and not exists (
      select 1 from jsonb_object_keys(payload) key
      where key not in ('min_bid','max_bid','max_daily_budget','max_changes_per_day',
                        'max_change_pct','cooldown_days','blast_radius_pct',
                        'max_data_age_hours','settlement_lag_days','profit_floor_pct')
    )
    and (not payload ? 'min_bid' or (payload->>'min_bid')::numeric >= 0)
    and (not payload ? 'max_bid' or (payload->>'max_bid')::numeric >= 0)
    and (not payload ? 'max_daily_budget' or (payload->>'max_daily_budget')::numeric >= 0)
    and (not payload ? 'max_changes_per_day'
         or (payload->>'max_changes_per_day')::numeric >= 0
         and (payload->>'max_changes_per_day')::numeric = trunc((payload->>'max_changes_per_day')::numeric))
    and (not (payload ? 'min_bid' and payload ? 'max_bid')
         or (payload->>'max_bid')::numeric >= (payload->>'min_bid')::numeric)
    and (not payload ? 'max_change_pct' or (payload->>'max_change_pct')::numeric > 0
         and (payload->>'max_change_pct')::numeric <= 1)
    and (not payload ? 'blast_radius_pct' or (payload->>'blast_radius_pct')::numeric > 0
         and (payload->>'blast_radius_pct')::numeric <= 1)
    and (not payload ? 'cooldown_days' or (payload->>'cooldown_days')::numeric between 0 and 90)
    and (not payload ? 'max_data_age_hours' or (payload->>'max_data_age_hours')::numeric between 1 and 720)
    and (not payload ? 'settlement_lag_days' or (payload->>'settlement_lag_days')::numeric between 0 and 30)
    and (not payload ? 'profit_floor_pct' or (payload->>'profit_floor_pct')::numeric between -1 and 1)
$$;
alter table objective_version add constraint objective_guardrails_valid check (validate_configuration_guardrails(guardrails));
alter table strategy_version add constraint strategy_guardrails_valid check (validate_configuration_guardrails(guardrails));

create function audit_configuration_version_created() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$ begin
  insert into configuration_version_event(
    tenant_id,entity_type,entity_id,event_type,actor_user_id,reason)
  values(new.tenant_id,tg_argv[0],new.id,'created',new.created_by,'version created');
  return new;
end $$;
create trigger objective_version_created after insert on objective_version
for each row execute function audit_configuration_version_created('objective');
create trigger strategy_version_created after insert on strategy_version
for each row execute function audit_configuration_version_created('strategy');

create function protect_configuration_version() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$ begin raise exception 'configuration versions and bindings are immutable'; end $$;
create trigger objective_version_immutable before update on objective_version for each row execute function protect_configuration_version();
create trigger strategy_version_immutable before update on strategy_version for each row execute function protect_configuration_version();
create trigger configuration_binding_immutable before update on configuration_run_binding for each row execute function protect_configuration_version();
create trigger configuration_event_immutable before update on configuration_version_event for each row execute function protect_configuration_version();

do $$ declare t text; begin
  foreach t in array array['objective_version','strategy_version','configuration_run_binding','configuration_version_event'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  end loop;
end $$;
grant select,insert on objective_version,strategy_version,configuration_run_binding,configuration_version_event to axaty_app;
grant execute on function validate_configuration_guardrails(jsonb) to axaty_app;
