-- Tenant-scoped operator experiment plans and linked outcome evidence.
create table action_experiment (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  name text not null check (btrim(name) <> '' and length(name) <= 160),
  hypothesis text not null check (btrim(hypothesis) <> '' and length(hypothesis) <= 4000),
  success_metric text not null check (btrim(success_metric) <> '' and length(success_metric) <= 120),
  control_description text not null check (btrim(control_description) <> '' and length(control_description) <= 2000),
  entity_type text not null check (btrim(entity_type) <> '' and length(entity_type) <= 80),
  entity_id text not null check (btrim(entity_id) <> '' and length(entity_id) <= 200),
  start_date date not null,
  end_date date,
  status text not null default 'planned' check (status in ('planned','running','completed','cancelled')),
  summary text check (summary is null or length(summary) <= 4000),
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (end_date is null or end_date >= start_date),
  check ((status in ('planned','running') and end_date is null) or status in ('completed','cancelled')),
  unique (id,tenant_id)
);

create table action_experiment_outcome (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  experiment_id uuid not null,
  action_id uuid,
  horizon_days integer,
  outcome_kind text not null check (outcome_kind in ('verified_action','operator_observation')),
  outcome text not null check (outcome in ('improved','worsened','neutral','inconclusive','confounded')),
  metric_name text not null check (btrim(metric_name) <> '' and length(metric_name) <= 120),
  metric_value numeric,
  sample_size integer check (sample_size is null or sample_size >= 0),
  observed_at timestamptz not null,
  evidence_note text not null check (btrim(evidence_note) <> '' and length(evidence_note) <= 4000),
  created_by uuid,
  created_at timestamptz not null default now(),
  foreign key(experiment_id,tenant_id) references action_experiment(id,tenant_id) on delete cascade,
  foreign key(action_id,tenant_id) references action(id,tenant_id) on delete cascade,
  check ((outcome_kind='verified_action' and action_id is not null and horizon_days is not null and horizon_days in (1,3,7,14,30))
      or (outcome_kind='operator_observation' and action_id is null and horizon_days is null)),
  unique(tenant_id,experiment_id,action_id,horizon_days,metric_name)
);

create index action_experiment_tenant_status_idx on action_experiment(tenant_id,status,start_date desc);
create index action_experiment_outcome_history_idx on action_experiment_outcome(tenant_id,metric_name,outcome,created_at desc);

alter table action_experiment enable row level security;
alter table action_experiment force row level security;
create policy tenant_isolation on action_experiment
  using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
  with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
alter table action_experiment_outcome enable row level security;
alter table action_experiment_outcome force row level security;
create policy tenant_isolation on action_experiment_outcome
  using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
  with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
grant select,insert,update on action_experiment to axaty_app;
grant select,insert on action_experiment_outcome to axaty_app;
