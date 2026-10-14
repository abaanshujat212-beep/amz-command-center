-- 0058_listing_validation.sql
-- Deterministic validation/provenance only. No Amazon listing mutation path.

create table listing_generation_record (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  project_id uuid not null,
  provider text not null check (btrim(provider) <> ''),
  model text not null check (btrim(model) <> ''),
  prompt_template_version text not null check (btrim(prompt_template_version) <> ''),
  prompt_sha256 text not null check (prompt_sha256 ~ '^[0-9a-f]{64}$'),
  source_fact_ids jsonb not null check (jsonb_typeof(source_fact_ids) = 'array'),
  keyword_bank jsonb not null check (jsonb_typeof(keyword_bank) = 'array'),
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (id, tenant_id),
  foreign key (project_id, tenant_id) references listing_project(id, tenant_id) on delete cascade
);

create table listing_validation_run (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  project_id uuid not null,
  draft_version_id uuid not null,
  validator_version text not null check (btrim(validator_version) <> ''),
  product_type text,
  ptd_contract_verified boolean not null default false,
  restrictions_status text not null check (restrictions_status in ('unknown','clear','restricted','blocked','error')),
  passed boolean not null,
  validated_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (id, tenant_id),
  foreign key (project_id, tenant_id) references listing_project(id, tenant_id) on delete cascade,
  foreign key (draft_version_id, tenant_id) references listing_draft_version(id, tenant_id) on delete restrict
);

create table listing_validation_issue (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  validation_run_id uuid not null,
  code text not null check (btrim(code) <> ''),
  field text not null check (btrim(field) <> ''),
  severity text not null check (severity in ('warning','error')),
  message text not null check (btrim(message) <> ''),
  created_at timestamptz not null default now(),
  foreign key (validation_run_id, tenant_id) references listing_validation_run(id, tenant_id) on delete cascade
);

create function protect_listing_validation_record() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$ begin raise exception 'listing generation and validation records are immutable'; end $$;
create trigger listing_generation_record_immutable before update on listing_generation_record for each row execute function protect_listing_validation_record();
create trigger listing_validation_run_immutable before update on listing_validation_run for each row execute function protect_listing_validation_record();
create trigger listing_validation_issue_immutable before update on listing_validation_issue for each row execute function protect_listing_validation_record();

create index listing_validation_draft_idx on listing_validation_run(tenant_id,draft_version_id,created_at desc);
create index listing_validation_issue_run_idx on listing_validation_issue(tenant_id,validation_run_id,severity);

do $$ declare t text; begin
  foreach t in array array['listing_generation_record','listing_validation_run','listing_validation_issue'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  end loop;
end $$;

grant select,insert on listing_generation_record,listing_validation_run,listing_validation_issue to axaty_app;
