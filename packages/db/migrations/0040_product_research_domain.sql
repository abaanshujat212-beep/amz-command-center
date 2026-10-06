-- 0040_product_research_domain.sql
-- Tenant-safe product research workflow. Market facts must remain attributable.

create table research_project (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  name text not null check (btrim(name) <> ''),
  status text not null default 'active' check (status in ('active','archived')),
  objective text,
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, name)
);

create table research_candidate (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  project_id uuid not null,
  candidate_kind text not null check (candidate_kind in ('own_catalog','market')),
  asin text,
  sku text,
  title text not null check (btrim(title) <> ''),
  status text not null default 'new' check (status in ('new','watchlist','shortlisted','rejected')),
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, tenant_id),
  foreign key (project_id, tenant_id) references research_project(id, tenant_id) on delete cascade,
  check (candidate_kind <> 'own_catalog' or asin is not null or sku is not null)
);

create unique index research_candidate_identity
  on research_candidate (tenant_id, project_id, candidate_kind, coalesce(asin,''), coalesce(sku,''), title);

create table research_assumption (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  candidate_id uuid not null,
  assumption_key text not null check (btrim(assumption_key) <> ''),
  version integer not null check (version > 0),
  value jsonb not null,
  rationale text not null check (btrim(rationale) <> ''),
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  foreign key (candidate_id, tenant_id) references research_candidate(id, tenant_id) on delete cascade,
  unique (tenant_id, candidate_id, assumption_key, version)
);

create table research_observation (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  candidate_id uuid not null,
  metric text not null check (btrim(metric) <> ''),
  numeric_value numeric,
  text_value text,
  unit text,
  provider text not null check (btrim(provider) <> ''),
  observed_at timestamptz not null,
  method text not null check (btrim(method) <> ''),
  evidence_scope jsonb not null check (jsonb_typeof(evidence_scope) = 'object'),
  completeness text not null check (completeness in ('complete','partial','blocked')),
  evidence_ref text not null check (btrim(evidence_ref) <> ''),
  created_at timestamptz not null default now(),
  foreign key (candidate_id, tenant_id) references research_candidate(id, tenant_id) on delete cascade,
  check ((numeric_value is null) <> (text_value is null)),
  unique (tenant_id, candidate_id, metric, provider, observed_at, evidence_ref)
);

create index research_project_status_idx on research_project (tenant_id, status, updated_at desc);
create index research_candidate_project_idx on research_candidate (tenant_id, project_id, status, updated_at desc);
create index research_observation_candidate_idx on research_observation (tenant_id, candidate_id, observed_at desc);

create function protect_research_evidence() returns trigger
language plpgsql security invoker set search_path = public, pg_temp as $$
begin
  raise exception 'research evidence and assumption versions are immutable';
end
$$;
create trigger research_observation_immutable before update on research_observation
for each row execute function protect_research_evidence();
create trigger research_assumption_immutable before update on research_assumption
for each row execute function protect_research_evidence();

do $$
declare t text;
begin
  foreach t in array array[
    'research_project','research_candidate','research_assumption','research_observation'
  ] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy tenant_isolation on %I using (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid) with check (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid)', t);
  end loop;
end $$;

grant select, insert, update, delete on research_project, research_candidate to axaty_app;
grant select, insert on research_assumption, research_observation to axaty_app;
