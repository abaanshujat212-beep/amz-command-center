-- Versioned, explainable PPC score formulas and immutable score evidence.
create table ppc_score_formula_version (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  formula_type text not null check (formula_type in ('health','opportunity')),
  version integer not null check (version > 0),
  weights jsonb not null check (jsonb_typeof(weights)='object' and weights <> '{}'::jsonb),
  explanation text not null check (btrim(explanation) <> ''),
  effective_from timestamptz not null default now(),
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique(tenant_id,formula_type,version), unique(id,tenant_id)
);

create table ppc_score_snapshot (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  formula_version_id uuid not null,
  score_type text not null check (score_type in ('health','opportunity')),
  scope_type text not null check (scope_type in ('account','portfolio','campaign')),
  scope_id text not null check (btrim(scope_id) <> ''),
  score numeric(5,2) check (score is null or score between 0 and 100),
  coverage numeric(5,2) not null check (coverage between 0 and 100),
  components jsonb not null check (jsonb_typeof(components)='array'),
  data_through date,
  calculated_at timestamptz not null default now(),
  unique(tenant_id,score_type,scope_type,scope_id,formula_version_id,data_through),
  foreign key(formula_version_id,tenant_id) references ppc_score_formula_version(id,tenant_id) on delete restrict
);

create function protect_ppc_score_evidence() returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$ begin
  raise exception 'PPC score formulas and snapshots are immutable; create a new version';
end $$;
-- UPDATE is blocked by trigger. DELETE is denied by grants while remaining
-- available to the database for tenant-erasure cascades.
create trigger ppc_score_formula_immutable before update on ppc_score_formula_version for each row execute function protect_ppc_score_evidence();
create trigger ppc_score_snapshot_immutable before update on ppc_score_snapshot for each row execute function protect_ppc_score_evidence();
create index ppc_score_snapshot_latest_idx on ppc_score_snapshot(tenant_id,scope_type,scope_id,score_type,calculated_at desc);

alter table ppc_score_formula_version enable row level security; alter table ppc_score_formula_version force row level security;
create policy tenant_isolation on ppc_score_formula_version using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
alter table ppc_score_snapshot enable row level security; alter table ppc_score_snapshot force row level security;
create policy tenant_isolation on ppc_score_snapshot using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
grant select,insert on ppc_score_formula_version,ppc_score_snapshot to axaty_app;
