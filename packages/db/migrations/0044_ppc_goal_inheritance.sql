-- 0044_ppc_goal_inheritance.sql
-- Dated PPC goal overrides with deterministic hierarchy precedence.

create extension if not exists btree_gist;

create table ppc_goal_override (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  scope_type text not null check (scope_type in (
    'account','portfolio','product_family','asin','campaign','ad_group','target','keyword'
  )),
  scope_id text not null check (btrim(scope_id) <> ''),
  effective_from date not null,
  effective_to date,
  target_acos numeric(8,6),
  min_acos numeric(8,6),
  max_acos numeric(8,6),
  target_roas numeric(12,6),
  acos_ceiling numeric(8,6),
  profit_floor numeric(8,6),
  reason text not null check (btrim(reason) <> ''),
  created_by uuid references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (id,tenant_id),
  check (effective_to is null or effective_to >= effective_from),
  check (num_nonnulls(target_acos,min_acos,max_acos,target_roas,acos_ceiling,profit_floor) > 0),
  check (target_acos is null or target_acos between 0 and 10),
  check (min_acos is null or min_acos between 0 and 10),
  check (max_acos is null or max_acos between 0 and 10),
  check (target_roas is null or target_roas > 0),
  check (acos_ceiling is null or acos_ceiling between 0 and 10),
  check (profit_floor is null or profit_floor between -1 and 1),
  check (min_acos is null or max_acos is null or min_acos <= max_acos),
  check (target_acos is null or min_acos is null or target_acos >= min_acos),
  check (target_acos is null or max_acos is null or target_acos <= max_acos),
  exclude using gist (
    tenant_id with =,
    scope_type with =,
    scope_id with =,
    daterange(effective_from,coalesce(effective_to,'infinity'::date),'[]') with &&
  )
);

create index ppc_goal_override_resolution_idx
  on ppc_goal_override(tenant_id,scope_type,scope_id,effective_from desc);

create table ppc_goal_override_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  override_id uuid not null,
  event_type text not null default 'created' check (event_type = 'created'),
  actor_user_id uuid references auth.auth_user(id) on delete restrict,
  reason text not null check (btrim(reason) <> ''),
  occurred_at timestamptz not null default now(),
  foreign key (override_id,tenant_id)
    references ppc_goal_override(id,tenant_id) on delete cascade
);

create function audit_ppc_goal_override_created() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$ begin
  insert into ppc_goal_override_event(tenant_id,override_id,actor_user_id,reason)
  values(new.tenant_id,new.id,new.created_by,new.reason);
  return new;
end $$;
create trigger ppc_goal_override_created after insert on ppc_goal_override
for each row execute function audit_ppc_goal_override_created();

create trigger ppc_goal_override_immutable before update on ppc_goal_override
for each row execute function protect_configuration_version();
create trigger ppc_goal_override_event_immutable before update on ppc_goal_override_event
for each row execute function protect_configuration_version();

do $$ declare t text; begin
  foreach t in array array['ppc_goal_override','ppc_goal_override_event'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  end loop;
end $$;

grant select,insert on ppc_goal_override,ppc_goal_override_event to axaty_app;
