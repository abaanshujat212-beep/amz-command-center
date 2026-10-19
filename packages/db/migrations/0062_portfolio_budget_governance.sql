-- Versioned portfolio spend governance. Configuration only; never mutates Amazon.
create table portfolio_budget_limit (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  scope_type text not null check (scope_type in ('account','portfolio')),
  scope_id text not null check (btrim(scope_id) <> ''),
  period_type text not null check (period_type in ('daily','weekly','monthly')),
  version integer not null check (version > 0),
  limit_amount numeric(16,2) not null check (limit_amount >= 0),
  currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
  timezone text not null check (btrim(timezone) <> ''),
  effective_from date not null, effective_to date,
  reason text not null check (btrim(reason) <> ''),
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique(id,tenant_id), unique(tenant_id,scope_type,scope_id,period_type,version),
  check (effective_to is null or effective_to >= effective_from),
  exclude using gist(tenant_id with =,scope_type with =,scope_id with =,period_type with =,
    daterange(effective_from,coalesce(effective_to,'infinity'::date),'[]') with &&)
);
create index portfolio_budget_resolution_idx on portfolio_budget_limit(tenant_id,scope_type,scope_id,period_type,effective_from desc);
create table portfolio_budget_limit_event (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  limit_id uuid not null, actor_user_id uuid not null references auth.auth_user(id) on delete restrict,
  event_type text not null default 'created' check(event_type='created'), reason text not null,
  occurred_at timestamptz not null default now(),
  foreign key(limit_id,tenant_id) references portfolio_budget_limit(id,tenant_id) on delete cascade
);
create function audit_portfolio_budget_limit() returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$ begin
  insert into portfolio_budget_limit_event(tenant_id,limit_id,actor_user_id,reason) values(new.tenant_id,new.id,new.created_by,new.reason); return new;
end $$;
create trigger portfolio_budget_limit_created after insert on portfolio_budget_limit for each row execute function audit_portfolio_budget_limit();
create trigger portfolio_budget_limit_immutable before update or delete on portfolio_budget_limit for each row execute function protect_configuration_version();
create trigger portfolio_budget_event_immutable before update or delete on portfolio_budget_limit_event for each row execute function protect_configuration_version();
do $$ declare t text; begin foreach t in array array['portfolio_budget_limit','portfolio_budget_limit_event'] loop
 execute format('alter table %I enable row level security',t); execute format('alter table %I force row level security',t);
 execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
end loop; end $$;
grant select,insert on portfolio_budget_limit,portfolio_budget_limit_event to axaty_app;
