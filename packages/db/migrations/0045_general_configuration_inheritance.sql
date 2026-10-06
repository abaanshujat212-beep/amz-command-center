-- 0045_general_configuration_inheritance.sql
-- Versioned system definitions and append-only tenant configuration overrides.

create table configuration_definition_version (
  id uuid primary key default gen_random_uuid(),
  key text not null check (key ~ '^[a-z][a-z0-9_]*$'),
  version integer not null check (version > 0),
  value_type text not null check (value_type in ('boolean','integer','number','string')),
  default_value jsonb not null,
  constraints jsonb not null default '{}'::jsonb check (jsonb_typeof(constraints)='object'),
  hard_guard boolean not null default false,
  effective_from timestamptz not null default now(),
  effective_to timestamptz,
  created_at timestamptz not null default now(),
  unique(key,version),
  check (effective_to is null or effective_to > effective_from)
);

create table configuration_override_version (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  scope_type text not null check (scope_type in ('tenant','marketplace','entity')),
  scope_id text not null check (btrim(scope_id) <> ''),
  version integer not null check (version > 0),
  operation text not null check (operation in ('apply','detach','rollback')),
  values jsonb not null default '{}'::jsonb check (jsonb_typeof(values)='object'),
  supersedes_id uuid,
  rollback_of_id uuid,
  reason text not null check (btrim(reason) <> ''),
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique(id,tenant_id),
  unique(tenant_id,scope_type,scope_id,version),
  foreign key(supersedes_id,tenant_id)
    references configuration_override_version(id,tenant_id) on delete restrict,
  foreign key(rollback_of_id,tenant_id)
    references configuration_override_version(id,tenant_id) on delete restrict,
  check ((operation='detach' and values='{}'::jsonb and rollback_of_id is null)
      or (operation='apply' and values<>'{}'::jsonb and rollback_of_id is null)
      or (operation='rollback' and values<>'{}'::jsonb and rollback_of_id is not null))
);

create index configuration_override_resolution_idx
  on configuration_override_version(tenant_id,scope_type,scope_id,version desc);

create function validate_configuration_override() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$
declare item record; definition record; actual_type text;
begin
  for item in select key,value from jsonb_each(new.values) loop
    select d.value_type,d.constraints,d.hard_guard into definition
      from configuration_definition_version d
     where d.key=item.key and d.effective_from <= now()
       and (d.effective_to is null or d.effective_to > now())
     order by d.version desc limit 1;
    if not found then raise exception 'unknown configuration key: %',item.key; end if;
    if definition.hard_guard then
      raise exception 'hard guard cannot be overridden: %',item.key;
    end if;
    actual_type := jsonb_typeof(item.value);
    if (definition.value_type='boolean' and actual_type<>'boolean')
       or (definition.value_type in ('integer','number') and actual_type<>'number')
       or (definition.value_type='string' and actual_type<>'string') then
      raise exception 'invalid type for configuration key: %',item.key;
    end if;
    if definition.value_type='integer'
       and (item.value#>>'{}')::numeric <> trunc((item.value#>>'{}')::numeric) then
      raise exception 'configuration key must be an integer: %',item.key;
    end if;
    if definition.value_type in ('integer','number')
       and definition.constraints ? 'minimum'
       and (item.value#>>'{}')::numeric < (definition.constraints->>'minimum')::numeric then
      raise exception 'configuration key is below minimum: %',item.key;
    end if;
    if definition.value_type in ('integer','number')
       and definition.constraints ? 'maximum'
       and (item.value#>>'{}')::numeric > (definition.constraints->>'maximum')::numeric then
      raise exception 'configuration key is above maximum: %',item.key;
    end if;
  end loop;
  return new;
end $$;
create trigger configuration_override_valid before insert on configuration_override_version
for each row execute function validate_configuration_override();
create trigger configuration_definition_immutable before update on configuration_definition_version
for each row execute function protect_configuration_version();
create trigger configuration_override_immutable before update on configuration_override_version
for each row execute function protect_configuration_version();

insert into configuration_definition_version(key,version,value_type,default_value,constraints,hard_guard,effective_from)
values
 ('automation_enabled',1,'boolean','false','{}',false,'2000-01-01'),
 ('dry_run',1,'boolean','true','{}',false,'2000-01-01'),
 ('target_acos_default',1,'number','0.35','{"minimum":0,"maximum":10}',false,'2000-01-01'),
 ('max_change_pct',1,'number','0.25','{"minimum":0.000001,"maximum":1}',false,'2000-01-01'),
 ('cooldown_days',1,'integer','3','{"minimum":0,"maximum":90}',false,'2000-01-01'),
 ('max_changes_per_day',1,'integer','50','{"minimum":0}',false,'2000-01-01'),
 ('max_budget_increase_per_day',1,'number','50','{"minimum":0}',false,'2000-01-01'),
 ('blast_radius_pct',1,'number','0.30','{"minimum":0.000001,"maximum":1}',false,'2000-01-01'),
 ('min_bid',1,'number','0.02','{"minimum":0}',false,'2000-01-01'),
 ('max_bid',1,'number','5.00','{"minimum":0}',false,'2000-01-01'),
 ('max_daily_budget',1,'number','100.00','{"minimum":0}',false,'2000-01-01'),
 ('max_data_age_hours',1,'integer','48','{"minimum":1,"maximum":720}',false,'2000-01-01'),
 ('settlement_lag_days',1,'integer','3','{"minimum":0,"maximum":30}',false,'2000-01-01'),
 ('allow_direct_amazon_mutation',1,'boolean','false','{}',true,'2000-01-01'),
 ('absolute_max_bid',1,'number','50','{"minimum":0}',true,'2000-01-01'),
 ('absolute_max_daily_budget',1,'number','10000','{"minimum":0}',true,'2000-01-01'),
 ('absolute_max_changes_per_day',1,'integer','500','{"minimum":0}',true,'2000-01-01');

alter table configuration_definition_version enable row level security;
alter table configuration_definition_version force row level security;
create policy configuration_definition_read on configuration_definition_version for select using (true);

alter table configuration_override_version enable row level security;
alter table configuration_override_version force row level security;
create policy tenant_isolation on configuration_override_version
  using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
  with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);

grant select on configuration_definition_version to axaty_app;
grant select,insert on configuration_override_version to axaty_app;

insert into configuration_override_version(
  tenant_id,scope_type,scope_id,version,operation,values,reason,created_by)
select ts.tenant_id,'tenant',ts.tenant_id::text,1,'apply',
       jsonb_build_object(
         'automation_enabled',ts.automation_enabled,
         'dry_run',ts.dry_run,
         'target_acos_default',ts.target_acos_default,
         'max_change_pct',ts.max_change_pct,
         'cooldown_days',ts.cooldown_days,
         'max_changes_per_day',ts.max_changes_per_day,
         'max_budget_increase_per_day',ts.max_budget_increase_per_day,
         'blast_radius_pct',ts.blast_radius_pct,
         'min_bid',ts.min_bid,
         'max_bid',ts.max_bid,
         'max_daily_budget',ts.max_daily_budget,
         'max_data_age_hours',ts.max_data_age_hours,
         'settlement_lag_days',ts.settlement_lag_days),
       'migrated from tenant_settings',
       (select tm.user_id from tenant_member tm
         join auth.auth_user u on u.id=tm.user_id
        where tm.tenant_id=ts.tenant_id and tm.role in ('owner','admin') limit 1)
  from tenant_settings ts
 where exists (
   select 1 from tenant_member tm join auth.auth_user u on u.id=tm.user_id
    where tm.tenant_id=ts.tenant_id and tm.role in ('owner','admin')
 );
