-- 0032_report_job_core.sql
-- Versioned report definitions and a tenant-scoped, observable async job lifecycle.

create table report_definition (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  code text not null check (btrim(code) <> ''),
  version integer not null check (version > 0),
  title text not null check (btrim(title) <> ''),
  source_contract text not null check (btrim(source_contract) <> ''),
  render_contract_version integer not null default 1 check (render_contract_version > 0),
  definition jsonb not null check (jsonb_typeof(definition) = 'object'),
  active boolean not null default true,
  created_by uuid references auth.auth_user(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (tenant_id, code, version),
  unique (id, tenant_id)
);

create table report_job (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  report_definition_id uuid not null,
  definition_code text not null,
  definition_version integer not null check (definition_version > 0),
  definition_snapshot jsonb not null check (jsonb_typeof(definition_snapshot) = 'object'),
  requested_by uuid references auth.auth_user(id) on delete set null,
  idempotency_key text not null check (btrim(idempotency_key) <> ''),
  date_from date not null,
  date_to date not null,
  filters jsonb not null default '{}'::jsonb check (jsonb_typeof(filters) = 'object'),
  output_format text not null check (output_format in ('csv','xlsx','pdf')),
  scope_version integer not null default 1 check (scope_version > 0),
  status text not null default 'queued'
    check (status in ('queued','running','succeeded','failed','canceled')),
  attempt integer not null default 0 check (attempt >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  worker_id text,
  queued_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  next_attempt_at timestamptz not null default now(),
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (report_definition_id, tenant_id)
    references report_definition(id, tenant_id) on delete restrict,
  unique (tenant_id, idempotency_key),
  unique (id, tenant_id),
  check (date_from <= date_to),
  check (
    (status = 'queued' and finished_at is null)
    or (status = 'running' and started_at is not null and finished_at is null)
    or (status in ('succeeded','failed','canceled') and finished_at is not null)
  )
);

create index idx_report_job_claim
  on report_job (tenant_id, next_attempt_at, queued_at)
  where status = 'queued';
create index idx_report_job_tenant_created
  on report_job (tenant_id, created_at desc);

create table report_job_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  report_job_id uuid not null,
  event_type text not null check (event_type in (
    'report.queued','report.started','report.succeeded',
    'report.failed','report.retry_queued','report.canceled'
  )),
  previous_state text,
  new_state text not null,
  attempt integer not null check (attempt >= 0),
  actor_type text not null check (actor_type in ('user','worker','system')),
  actor_id text,
  dedupe_key text not null,
  metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object'),
  occurred_at timestamptz not null default now(),
  foreign key (report_job_id, tenant_id)
    references report_job(id, tenant_id) on delete restrict,
  unique (tenant_id, report_job_id, event_type, attempt, dedupe_key)
);

create index idx_report_job_event_job_at
  on report_job_event (tenant_id, report_job_id, occurred_at desc);

create function protect_report_definition_version()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  raise exception 'report definitions are immutable; create a new version';
end
$$;

create trigger report_definition_immutable
before update or delete on report_definition
for each row execute function protect_report_definition_version();

create function enforce_report_job_transition()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  if new.tenant_id <> old.tenant_id
     or new.report_definition_id <> old.report_definition_id
     or new.definition_code <> old.definition_code
     or new.definition_version <> old.definition_version
     or new.definition_snapshot <> old.definition_snapshot
     or new.requested_by is distinct from old.requested_by
     or new.idempotency_key <> old.idempotency_key
     or new.date_from <> old.date_from
     or new.date_to <> old.date_to
     or new.filters <> old.filters
     or new.output_format <> old.output_format
     or new.scope_version <> old.scope_version
     or new.max_attempts <> old.max_attempts then
    raise exception 'report job scope is immutable';
  end if;

  if old.status in ('succeeded','canceled') then
    raise exception 'terminal report job is immutable';
  end if;

  if new.status <> old.status then
    if not (
      (old.status = 'queued' and new.status in ('running','canceled'))
      or (old.status = 'running' and new.status in ('succeeded','failed'))
      or (old.status = 'failed' and new.status = 'queued' and old.attempt < old.max_attempts)
    ) then
      raise exception 'invalid report job transition: % -> %', old.status, new.status;
    end if;
  end if;

  if old.status = 'queued' and new.status = 'running' then
    if new.attempt <> old.attempt + 1 then
      raise exception 'claim must increment report attempt exactly once';
    end if;
  elsif new.attempt <> old.attempt then
    raise exception 'report attempt changes only during claim';
  end if;

  new.updated_at := now();
  return new;
end
$$;

create trigger report_job_transition_guard
before update on report_job
for each row execute function enforce_report_job_transition();

alter table report_definition enable row level security;
alter table report_definition force row level security;
create policy tenant_isolation on report_definition
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

alter table report_job enable row level security;
alter table report_job force row level security;
create policy tenant_isolation on report_job
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

alter table report_job_event enable row level security;
alter table report_job_event force row level security;
create policy tenant_isolation on report_job_event
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

revoke all on report_definition, report_job, report_job_event from axaty_app;
grant select, insert on report_definition to axaty_app;
grant select, insert, update on report_job to axaty_app;
grant select, insert on report_job_event to axaty_app;
