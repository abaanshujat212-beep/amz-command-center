-- 0042_listing_studio_foundation.sql
-- Human-reviewed listing drafts; this migration creates no Amazon write path.

create table listing_project (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  research_candidate_id uuid,
  name text not null check (btrim(name) <> ''),
  asin text,
  sku text,
  marketplace text not null default 'UK' check (btrim(marketplace) <> ''),
  review_state text not null default 'draft' check (review_state in ('draft','in_review','approved','changes_requested','archived')),
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, name),
  foreign key (research_candidate_id, tenant_id) references research_candidate(id, tenant_id) on delete restrict
);

create table listing_product_fact (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  project_id uuid not null,
  fact_key text not null check (btrim(fact_key) <> ''),
  value jsonb not null,
  source_type text not null check (source_type in ('manual','catalog','provider','research_evidence')),
  source_ref text not null check (btrim(source_ref) <> ''),
  observed_at timestamptz not null,
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (id, tenant_id),
  foreign key (project_id, tenant_id) references listing_project(id, tenant_id) on delete cascade,
  unique (tenant_id, project_id, fact_key, source_type, source_ref, observed_at)
);

create table listing_keyword_plan_version (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  project_id uuid not null,
  version integer not null check (version > 0),
  keywords jsonb not null check (jsonb_typeof(keywords) = 'array'),
  source_refs jsonb not null check (jsonb_typeof(source_refs) = 'array'),
  rationale text not null check (btrim(rationale) <> ''),
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (id, tenant_id),
  foreign key (project_id, tenant_id) references listing_project(id, tenant_id) on delete cascade,
  unique (tenant_id, project_id, version)
);

create table listing_draft_version (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  project_id uuid not null,
  version integer not null check (version > 0),
  previous_version_id uuid,
  title text not null default '',
  bullets jsonb not null default '[]'::jsonb check (jsonb_typeof(bullets) = 'array'),
  description text not null default '',
  backend_terms jsonb not null default '[]'::jsonb check (jsonb_typeof(backend_terms) = 'array'),
  keyword_plan_version_id uuid,
  origin text not null default 'human' check (origin in ('human','ai_assisted','imported')),
  generation_ref text,
  change_summary text not null check (btrim(change_summary) <> ''),
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (id, tenant_id),
  foreign key (project_id, tenant_id) references listing_project(id, tenant_id) on delete cascade,
  foreign key (previous_version_id, tenant_id) references listing_draft_version(id, tenant_id) on delete restrict,
  foreign key (keyword_plan_version_id, tenant_id) references listing_keyword_plan_version(id, tenant_id) on delete restrict,
  unique (tenant_id, project_id, version),
  check (previous_version_id is null or previous_version_id <> id),
  check (origin <> 'ai_assisted' or btrim(generation_ref) <> '')
);

create table listing_draft_fact (
  tenant_id uuid not null references tenant(id) on delete cascade,
  draft_version_id uuid not null,
  product_fact_id uuid not null,
  primary key (tenant_id,draft_version_id,product_fact_id),
  foreign key (draft_version_id,tenant_id) references listing_draft_version(id,tenant_id) on delete cascade,
  foreign key (product_fact_id,tenant_id) references listing_product_fact(id,tenant_id) on delete restrict
);

create table listing_review_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  project_id uuid not null,
  draft_version_id uuid not null,
  decision text not null check (decision in ('submitted','approved','changes_requested','returned_to_draft')),
  comment text,
  actor_user_id uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  foreign key (project_id, tenant_id) references listing_project(id, tenant_id) on delete cascade,
  foreign key (draft_version_id, tenant_id) references listing_draft_version(id, tenant_id) on delete restrict
);

create function protect_listing_version() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$ begin raise exception 'listing versions and review events are immutable'; end $$;
create trigger listing_fact_immutable before update on listing_product_fact for each row execute function protect_listing_version();
create trigger listing_keyword_version_immutable before update on listing_keyword_plan_version for each row execute function protect_listing_version();
create trigger listing_draft_version_immutable before update on listing_draft_version for each row execute function protect_listing_version();
create trigger listing_review_event_immutable before update on listing_review_event for each row execute function protect_listing_version();

create index listing_project_state_idx on listing_project(tenant_id,review_state,updated_at desc);
create index listing_draft_project_idx on listing_draft_version(tenant_id,project_id,version desc);
create index listing_review_project_idx on listing_review_event(tenant_id,project_id,created_at desc);

do $$ declare t text; begin
  foreach t in array array['listing_project','listing_product_fact','listing_keyword_plan_version','listing_draft_version','listing_draft_fact','listing_review_event'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  end loop;
end $$;
grant select,insert,update,delete on listing_project to axaty_app;
grant select,insert on listing_product_fact,listing_keyword_plan_version,listing_draft_version,listing_draft_fact,listing_review_event to axaty_app;
