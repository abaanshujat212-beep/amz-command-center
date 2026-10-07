-- 0047_search_term_harvest_lineage.sql
-- Deterministic search-term harvest routing and durable source -> destination lineage.

create table search_term_brand_term (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  term text not null check (btrim(term) <> '' and term = lower(btrim(term))),
  brand_class text not null check (brand_class in ('own_brand','competitor')),
  created_by uuid references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (tenant_id,term)
);

create table search_term_harvest_route (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  code text not null check (code ~ '^[a-z][a-z0-9_]*$'),
  priority integer not null default 100 check (priority between 1 and 10000),
  asin text not null default '*' check (asin = '*' or asin ~ '^[A-Z0-9]{10}$'),
  brand_class text not null default '*'
    check (brand_class in ('*','own_brand','competitor','generic')),
  match_type text not null check (match_type in ('exact','product')),
  strategy_code text not null default '*' check (btrim(strategy_code) <> ''),
  funnel_purpose text not null
    check (funnel_purpose in ('brand_defense','conquest','performance')),
  destination_campaign_id text not null check (btrim(destination_campaign_id) <> ''),
  destination_ad_group_id text not null check (btrim(destination_ad_group_id) <> ''),
  enabled boolean not null default true,
  created_by uuid references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (id,tenant_id),
  unique (tenant_id,code)
);

create index search_term_harvest_route_lookup_idx
  on search_term_harvest_route(tenant_id,match_type,funnel_purpose) where enabled;

create table search_term_harvest_lineage (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  run_id uuid not null,
  evaluation_id uuid not null references rule_evaluation(id) on delete cascade,
  action_id uuid not null references action(id) on delete cascade,
  route_id uuid not null,
  route_code text not null,
  search_term text not null check (btrim(search_term) <> ''),
  normalized_term text not null check (btrim(normalized_term) <> ''),
  asin text,
  brand_class text not null check (brand_class in ('own_brand','competitor','generic')),
  funnel_purpose text not null
    check (funnel_purpose in ('brand_defense','conquest','performance')),
  strategy_code text not null,
  source_campaign_id text not null,
  source_ad_group_id text not null,
  source_keyword_id text,
  source_match_type text,
  destination_campaign_id text not null,
  destination_ad_group_id text not null,
  destination_match_type text not null check (destination_match_type in ('exact','product')),
  routing_reason text not null check (btrim(routing_reason) <> ''),
  evidence jsonb not null check (jsonb_typeof(evidence)='object'),
  created_at timestamptz not null default now(),
  unique (tenant_id,action_id),
  foreign key (route_id,tenant_id) references search_term_harvest_route(id,tenant_id)
);

create index search_term_harvest_lineage_term_idx
  on search_term_harvest_lineage(tenant_id,normalized_term,destination_match_type);

create trigger search_term_harvest_lineage_immutable
before update on search_term_harvest_lineage
for each row execute function protect_configuration_version();

do $$ declare t text; begin
  foreach t in array array[
    'search_term_brand_term','search_term_harvest_route','search_term_harvest_lineage'
  ] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  end loop;
end $$;

grant select,insert,update,delete on search_term_brand_term,search_term_harvest_route to axaty_app;
grant select,insert on search_term_harvest_lineage to axaty_app;
