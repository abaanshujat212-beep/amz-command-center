-- 0054_dashboard_studio_contracts.sql
-- Versioned, read-only AXATY templates and tenant/actor-scoped dashboard metadata.

create function dashboard_definition_valid(definition jsonb) returns boolean
language plpgsql immutable strict set search_path=public,pg_temp as $$
declare widget jsonb; filter jsonb;
begin
  if jsonb_typeof(definition) <> 'object'
    or definition->>'schemaVersion' <> '1'
    or jsonb_typeof(definition->'widgets') <> 'array'
    or jsonb_array_length(definition->'widgets') > 50
    or (definition ? 'globalFilters' and jsonb_typeof(definition->'globalFilters') <> 'array') then
    return false;
  end if;
  for widget in select value from jsonb_array_elements(definition->'widgets') loop
    if jsonb_typeof(widget) <> 'object'
      or coalesce(widget->>'id','') !~ '^[a-z][a-z0-9_-]{0,63}$'
      or coalesce(widget->>'type','') not in ('scorecard','table','timeseries','bar')
      or coalesce(widget->>'query','') not in ('dashboard.summary','campaign.performance','search_terms.performance','product.economics','sqp.opportunities','pipeline.health')
      or jsonb_typeof(widget->'layout') <> 'object'
      or not (widget->'layout' ?& array['x','y','w','h'])
      or (widget->'layout'->>'w')::integer not between 1 and 12
      or (widget->'layout'->>'h')::integer not between 1 and 20 then
      return false;
    end if;
    if widget ? 'filters' then
      if jsonb_typeof(widget->'filters') <> 'array' then return false; end if;
      for filter in select value from jsonb_array_elements(widget->'filters') loop
        if coalesce(filter->>'field','') not in ('marketplace','dateRange','campaignId','asin','sku','status')
          or coalesce(filter->>'operator','') not in ('eq','in','between','gte','lte')
          or not (filter ? 'value') then return false;
        end if;
      end loop;
    end if;
  end loop;
  for filter in select value from jsonb_array_elements(coalesce(definition->'globalFilters','[]'::jsonb)) loop
    if coalesce(filter->>'field','') not in ('marketplace','dateRange','campaignId','asin','sku','status')
      or coalesce(filter->>'operator','') not in ('eq','in','between','gte','lte')
      or not (filter ? 'value') then return false;
    end if;
  end loop;
  return true;
exception when others then return false;
end $$;

create table dashboard_template (
  template_key text primary key check(template_key ~ '^[a-z][a-z0-9_-]{1,63}$'),
  name text not null check(btrim(name) <> ''), description text,
  current_version integer not null check(current_version > 0),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table dashboard_template_version (
  template_key text not null references dashboard_template(template_key) on delete restrict,
  version integer not null check(version > 0),
  definition jsonb not null check(dashboard_definition_valid(definition)),
  release_notes text not null check(btrim(release_notes) <> ''), created_at timestamptz not null default now(),
  primary key(template_key,version)
);

create table dashboard (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  name text not null check(btrim(name) <> ''), visibility text not null check(visibility in('private','team')),
  owner_user_id uuid not null references auth.auth_user(id) on delete restrict,
  source_template_key text, source_template_version integer,
  current_version integer not null default 1 check(current_version > 0), is_archived boolean not null default false,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique(id,tenant_id),
  foreign key(source_template_key,source_template_version) references dashboard_template_version(template_key,version) on delete restrict,
  check((source_template_key is null)=(source_template_version is null))
);
create table dashboard_version (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  dashboard_id uuid not null, version integer not null check(version > 0),
  definition jsonb not null check(dashboard_definition_valid(definition)), change_summary text not null check(btrim(change_summary) <> ''),
  created_by uuid not null references auth.auth_user(id) on delete restrict, created_at timestamptz not null default now(),
  unique(id,tenant_id), unique(tenant_id,dashboard_id,version),
  foreign key(dashboard_id,tenant_id) references dashboard(id,tenant_id) on delete cascade
);
create table dashboard_default (
  tenant_id uuid not null references tenant(id) on delete cascade,
  user_id uuid not null references auth.auth_user(id) on delete cascade, dashboard_id uuid not null,
  created_at timestamptz not null default now(), primary key(tenant_id,user_id),
  foreign key(dashboard_id,tenant_id) references dashboard(id,tenant_id) on delete cascade
);

create function current_dashboard_user() returns uuid language sql stable as $$
  select nullif(current_setting('app.user_id',true),'')::uuid
$$;
create function current_dashboard_role() returns text language sql stable as $$
  select nullif(current_setting('app.tenant_role',true),'')
$$;
create function set_dashboard_actor(p_user uuid,p_role text) returns void language plpgsql as $$ begin
  if p_role not in ('owner','admin','user','analyst','viewer') then raise exception 'invalid tenant role'; end if;
  perform set_config('app.user_id',p_user::text,true); perform set_config('app.tenant_role',p_role,true);
end $$;
create function dashboard_visible(p_tenant uuid,p_dashboard uuid) returns boolean language sql stable security invoker set search_path=public,pg_temp as $$
  select exists(select 1 from dashboard d where d.tenant_id=p_tenant and d.id=p_dashboard and (d.visibility='team' or d.owner_user_id=current_dashboard_user()))
$$;
create function dashboard_editable(p_tenant uuid,p_dashboard uuid) returns boolean language sql stable security invoker set search_path=public,pg_temp as $$
  select exists(select 1 from dashboard d where d.tenant_id=p_tenant and d.id=p_dashboard and (d.owner_user_id=current_dashboard_user() or current_dashboard_role() in('owner','admin')))
$$;

alter table dashboard enable row level security; alter table dashboard force row level security;
create policy dashboard_read on dashboard for select using(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid and (visibility='team' or owner_user_id=current_dashboard_user()));
create policy dashboard_create on dashboard for insert with check(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid and owner_user_id=current_dashboard_user());
create policy dashboard_change on dashboard for update using(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid and (owner_user_id=current_dashboard_user() or current_dashboard_role() in('owner','admin'))) with check(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
create policy dashboard_remove on dashboard for delete using(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid and (owner_user_id=current_dashboard_user() or current_dashboard_role() in('owner','admin')));

alter table dashboard_version enable row level security; alter table dashboard_version force row level security;
create policy dashboard_version_read on dashboard_version for select using(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid and dashboard_visible(tenant_id,dashboard_id));
create policy dashboard_version_create on dashboard_version for insert with check(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid and dashboard_editable(tenant_id,dashboard_id));
alter table dashboard_default enable row level security; alter table dashboard_default force row level security;
create policy dashboard_default_own on dashboard_default using(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid and user_id=current_dashboard_user()) with check(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid and user_id=current_dashboard_user() and dashboard_visible(tenant_id,dashboard_id));

create function protect_dashboard_version() returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$ begin raise exception 'dashboard versions are immutable'; end $$;
create trigger dashboard_version_immutable before update on dashboard_version for each row execute function protect_dashboard_version();
create trigger dashboard_template_version_immutable before update or delete on dashboard_template_version for each row execute function protect_dashboard_version();
create index dashboard_visible_idx on dashboard(tenant_id,visibility,owner_user_id,updated_at desc);
create index dashboard_version_latest_idx on dashboard_version(tenant_id,dashboard_id,version desc);

revoke all on dashboard_template,dashboard_template_version from axaty_app;
grant select on dashboard_template,dashboard_template_version to axaty_app;
grant select,insert,update,delete on dashboard to axaty_app;
grant select,insert on dashboard_version to axaty_app;
grant select,insert,update,delete on dashboard_default to axaty_app;
grant execute on function set_dashboard_actor(uuid,text) to axaty_app;

insert into dashboard_template(template_key,name,description,current_version) values
('operator-overview','Operator overview','Performance, approvals and pipeline health.',1),
('ppc-performance','PPC performance','Campaign and search-term performance.',1);
insert into dashboard_template_version(template_key,version,definition,release_notes) values
('operator-overview',1,'{"schemaVersion":1,"widgets":[{"id":"summary","type":"scorecard","query":"dashboard.summary","layout":{"x":0,"y":0,"w":12,"h":3}},{"id":"health","type":"table","query":"pipeline.health","layout":{"x":0,"y":3,"w":12,"h":5}}],"globalFilters":[]}'::jsonb,'Initial AXATY template'),
('ppc-performance',1,'{"schemaVersion":1,"widgets":[{"id":"campaigns","type":"table","query":"campaign.performance","layout":{"x":0,"y":0,"w":7,"h":6}},{"id":"terms","type":"table","query":"search_terms.performance","layout":{"x":7,"y":0,"w":5,"h":6}}],"globalFilters":[{"field":"dateRange","operator":"between","value":["P30D","P0D"]}]}'::jsonb,'Initial AXATY template');
