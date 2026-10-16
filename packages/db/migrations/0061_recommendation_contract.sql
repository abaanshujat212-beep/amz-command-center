-- 0061_recommendation_contract.sql
-- Canonical recommendation metadata on the existing action queue.

alter table rule_evaluation
  add column recommendation_type text,
  add column confidence numeric(5,4),
  add column risk text,
  add column lookback_days integer,
  add column objective_snapshot jsonb,
  add column strategy_snapshot jsonb,
  add column economic_effect jsonb,
  add column expected_behavior jsonb,
  add constraint rule_evaluation_recommendation_type_check check (recommendation_type is null or recommendation_type in (
    'bid_adjustment','budget_adjustment','entity_state','negative_targeting','keyword_harvest','placement_adjustment','diagnostic'
  )),
  add constraint rule_evaluation_confidence_check check (confidence is null or confidence between 0 and 1),
  add constraint rule_evaluation_risk_check check (risk is null or risk in ('low','medium','high','critical')),
  add constraint rule_evaluation_lookback_check check (lookback_days is null or lookback_days > 0);
alter table rule_evaluation add constraint uq_rule_evaluation_id_tenant unique(id,tenant_id);

alter table action
  add column recommendation_type text,
  add column confidence numeric(5,4),
  add column risk text,
  add column lookback_days integer,
  add column objective_snapshot jsonb,
  add column strategy_snapshot jsonb,
  add column economic_effect jsonb,
  add column expected_behavior jsonb,
  add constraint action_recommendation_type_check check (recommendation_type is null or recommendation_type in (
    'bid_adjustment','budget_adjustment','entity_state','negative_targeting','keyword_harvest','placement_adjustment','diagnostic'
  )),
  add constraint action_confidence_check check (confidence is null or confidence between 0 and 1),
  add constraint action_risk_check check (risk is null or risk in ('low','medium','high','critical')),
  add constraint action_lookback_check check (lookback_days is null or lookback_days > 0);

create function protect_action_recommendation_metadata() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$ begin
  if row(old.recommendation_type,old.confidence,old.risk,old.lookback_days,old.objective_snapshot,
         old.strategy_snapshot,old.economic_effect,old.expected_behavior)
     is distinct from
     row(new.recommendation_type,new.confidence,new.risk,new.lookback_days,new.objective_snapshot,
         new.strategy_snapshot,new.economic_effect,new.expected_behavior) then
    raise exception 'recommendation metadata is immutable';
  end if;
  return new;
end $$;
create trigger action_recommendation_metadata_immutable before update on action
for each row execute function protect_action_recommendation_metadata();
create trigger rule_evaluation_recommendation_metadata_immutable before update on rule_evaluation
for each row execute function protect_action_recommendation_metadata();

create table optimizer_run (
  id uuid primary key,
  tenant_id uuid not null references tenant(id) on delete cascade,
  run_key text not null check (btrim(run_key) <> ''),
  engine_version text not null check (btrim(engine_version) <> ''),
  configuration_version text not null check (btrim(configuration_version) <> ''),
  objective_snapshot jsonb not null check (jsonb_typeof(objective_snapshot)='object'),
  strategy_snapshot jsonb not null check (jsonb_typeof(strategy_snapshot)='object'),
  status text not null default 'running' check (status in ('running','succeeded','partial','failed')),
  entities_evaluated integer not null default 0 check (entities_evaluated >= 0),
  recommendations_emitted integer not null default 0 check (recommendations_emitted >= 0),
  entities_skipped integer not null default 0 check (entities_skipped >= 0),
  failures integer not null default 0 check (failures >= 0),
  started_at timestamptz not null,
  finished_at timestamptz,
  duration_ms integer check (duration_ms is null or duration_ms >= 0),
  unique(id,tenant_id),
  unique(tenant_id,run_key),
  check ((status='running' and finished_at is null and duration_ms is null)
      or (status<>'running' and finished_at is not null and duration_ms is not null))
);

create table recommendation_evidence (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  optimizer_run_id uuid not null,
  evaluation_id uuid not null,
  action_id uuid references action(id) on delete set null,
  evidence_kind text not null check (evidence_kind in ('metric_snapshot','freshness','economics','dependency','capability')),
  source_type text not null check (btrim(source_type) <> ''),
  source_ref text not null check (btrim(source_ref) <> ''),
  observed_at timestamptz not null,
  data_through date,
  completeness text not null check (completeness in ('complete','partial','missing','blocked')),
  metric_keys jsonb not null default '[]'::jsonb check (jsonb_typeof(metric_keys)='array'),
  detail jsonb not null default '{}'::jsonb check (jsonb_typeof(detail)='object'),
  created_at timestamptz not null default now(),
  unique(id,tenant_id),
  unique(tenant_id,optimizer_run_id,evaluation_id,evidence_kind,source_ref),
  foreign key(optimizer_run_id,tenant_id) references optimizer_run(id,tenant_id) on delete cascade,
  foreign key(evaluation_id,tenant_id) references rule_evaluation(id,tenant_id) on delete cascade,
  foreign key(action_id,tenant_id) references action(id,tenant_id) on delete cascade
);

create function protect_optimizer_run() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$ begin
  if old.status <> 'running' then raise exception 'optimizer run is already finalized'; end if;
  if new.status = 'running' or new.id<>old.id or new.tenant_id<>old.tenant_id or new.run_key<>old.run_key
     or new.engine_version<>old.engine_version or new.configuration_version<>old.configuration_version
     or new.objective_snapshot<>old.objective_snapshot or new.strategy_snapshot<>old.strategy_snapshot
     or new.started_at<>old.started_at then raise exception 'optimizer run context is immutable'; end if;
  return new;
end $$;
create trigger optimizer_run_finalize_once before update on optimizer_run for each row execute function protect_optimizer_run();
-- Application role has no DELETE grant; allow FK cascades for tenant erasure.
create trigger recommendation_evidence_immutable before update on recommendation_evidence
for each row execute function protect_research_evidence();

create index recommendation_filter_idx on action(tenant_id,recommendation_type,status,risk,requested_at desc);
create index recommendation_entity_idx on action(tenant_id,entity_type,entity_id,requested_at desc);
create index recommendation_evidence_action_idx on recommendation_evidence(tenant_id,action_id,created_at);

alter table optimizer_run enable row level security;
alter table optimizer_run force row level security;
create policy tenant_isolation on optimizer_run using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
alter table recommendation_evidence enable row level security;
alter table recommendation_evidence force row level security;
create policy tenant_isolation on recommendation_evidence using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
grant select,insert,update on optimizer_run to axaty_app;
grant select,insert on recommendation_evidence to axaty_app;
