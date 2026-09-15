-- 0028_workspace_entitlements.sql
-- Workspace membership sits above independent tenant/RLS boundaries.
-- Application code cannot query these tables directly; discovery requires a valid session.

create table workspace (
  id uuid primary key default gen_random_uuid(),
  name text not null check (btrim(name) <> ''),
  slug text not null unique check (btrim(slug) <> ''),
  status text not null default 'active'
    check (status in ('active','suspended','archived')),
  created_at timestamptz not null default now()
);

create table workspace_entitlement (
  workspace_id uuid primary key references workspace(id) on delete cascade,
  portfolio_enabled boolean not null default false,
  cross_account_summary_enabled boolean not null default false,
  portfolio_alerts_enabled boolean not null default false,
  max_connected_accounts integer not null default 1
    check (max_connected_accounts between 1 and 1000),
  max_team_seats integer not null default 1
    check (max_team_seats between 1 and 1000),
  updated_at timestamptz not null default now()
);

create table workspace_member (
  workspace_id uuid not null references workspace(id) on delete cascade,
  user_id uuid not null references auth.auth_user(id) on delete cascade,
  role text not null check (role in ('owner','admin','operator','analyst','viewer')),
  can_view_portfolio boolean not null default false,
  can_operate_tenants boolean not null default false,
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);

create unique index workspace_one_owner
  on workspace_member(workspace_id) where role = 'owner';

create table workspace_tenant (
  workspace_id uuid not null references workspace(id) on delete cascade,
  tenant_id uuid not null references tenant(id) on delete cascade,
  client_label text,
  created_at timestamptz not null default now(),
  primary key (workspace_id, tenant_id)
);

create index workspace_tenant_tenant_idx on workspace_tenant(tenant_id, workspace_id);

create function initialize_workspace_entitlement()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  insert into workspace_entitlement(workspace_id) values (new.id);
  return new;
end
$$;

create trigger workspace_initialize_entitlement
after insert on workspace
for each row execute function initialize_workspace_entitlement();

create function enforce_workspace_seat_limit()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  allowed integer;
  used integer;
begin
  select max_team_seats into allowed
    from workspace_entitlement where workspace_id = new.workspace_id for update;
  if allowed is null then
    raise exception 'workspace entitlement is missing';
  end if;
  select count(*) into used from workspace_member where workspace_id = new.workspace_id;
  if used >= allowed then
    raise exception 'workspace team seat limit exceeded';
  end if;
  return new;
end
$$;

create trigger workspace_member_limit
before insert on workspace_member
for each row execute function enforce_workspace_seat_limit();

create function enforce_workspace_account_limit()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  allowed integer;
  used integer;
begin
  select max_connected_accounts into allowed
    from workspace_entitlement where workspace_id = new.workspace_id for update;
  if allowed is null then
    raise exception 'workspace entitlement is missing';
  end if;
  select count(*) into used from workspace_tenant where workspace_id = new.workspace_id;
  if used >= allowed then
    raise exception 'workspace connected account limit exceeded';
  end if;
  return new;
end
$$;

create trigger workspace_tenant_limit
before insert on workspace_tenant
for each row execute function enforce_workspace_account_limit();

create function session_workspaces(p_token text)
returns table(
  workspace_id text,
  name text,
  slug text,
  role text,
  can_view_portfolio boolean,
  can_operate_tenants boolean,
  portfolio_enabled boolean,
  cross_account_summary_enabled boolean,
  portfolio_alerts_enabled boolean,
  max_connected_accounts integer,
  max_team_seats integer
)
language sql
security definer
set search_path = pg_catalog
set row_security = off
as $$
  select w.id::text, w.name, w.slug, m.role,
         m.can_view_portfolio, m.can_operate_tenants,
         e.portfolio_enabled, e.cross_account_summary_enabled,
         e.portfolio_alerts_enabled, e.max_connected_accounts, e.max_team_seats
    from auth.auth_session s
    join public.workspace_member m on m.user_id = s.user_id
    join public.workspace w on w.id = m.workspace_id
    join public.workspace_entitlement e on e.workspace_id = w.id
   where s.token = p_token and s.expires_at > now() and w.status = 'active'
   order by w.name, w.id
$$;

revoke all on workspace, workspace_entitlement, workspace_member, workspace_tenant
  from public, axaty_app;
revoke all on function initialize_workspace_entitlement() from public, axaty_app;
revoke all on function enforce_workspace_seat_limit() from public, axaty_app;
revoke all on function enforce_workspace_account_limit() from public, axaty_app;
revoke all on function session_workspaces(text) from public;
grant execute on function session_workspaces(text) to axaty_app;
