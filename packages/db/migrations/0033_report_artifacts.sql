-- 0033_report_artifacts.sql
-- Reproducible, tenant-scoped metadata for privately stored report artifacts.

create table report_artifact (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  report_job_id uuid not null,
  output_format text not null check (output_format in ('csv','xlsx','pdf')),
  media_type text not null check (btrim(media_type) <> ''),
  file_extension text not null check (file_extension in ('csv','xlsx','pdf')),
  render_contract_version integer not null check (render_contract_version > 0),
  storage_key text not null check (
    btrim(storage_key) <> '' and position('://' in storage_key) = 0
  ),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  source_data_sha256 text not null check (source_data_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size bigint not null check (byte_size > 0),
  row_count bigint not null check (row_count >= 0),
  reconciliation jsonb not null check (jsonb_typeof(reconciliation) = 'object'),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  foreign key (report_job_id, tenant_id)
    references report_job(id, tenant_id) on delete cascade,
  unique (tenant_id, report_job_id),
  unique (tenant_id, storage_key),
  check (expires_at > created_at)
);

create index idx_report_artifact_tenant_expiry
  on report_artifact (tenant_id, expires_at);

create function protect_report_artifact_metadata()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  raise exception 'report artifact metadata is immutable';
end
$$;

create trigger report_artifact_immutable
before update on report_artifact
for each row execute function protect_report_artifact_metadata();

alter table report_artifact enable row level security;
alter table report_artifact force row level security;
create policy tenant_isolation on report_artifact
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

revoke all on report_artifact from axaty_app;
grant select, insert on report_artifact to axaty_app;
