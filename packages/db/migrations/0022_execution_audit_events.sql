-- Immutable, tenant-scoped execution history for action workers and verification.
alter table action add constraint action_id_tenant_unique unique (id, tenant_id);

create table action_execution_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  marketplace_id text not null default 'A1F83G8C2ARO7P',
  account_scope text,
  action_id uuid not null,
  actor_type text not null check (actor_type in ('worker','system','user')),
  actor_id text,
  event_type text not null check (event_type in (
    'action.live_apply.requested','action.live_apply.started',
    'action.live_apply.succeeded','action.live_apply.failed','action.live_apply.drift_blocked',
    'action.retry.scheduled','action.retry.attempted','action.retry.exhausted',
    'action.rollback.requested','action.rollback.succeeded','action.rollback.failed',
    'action.verification.scheduled','action.verification.checkpoint',
    'action.verification.result','action.verification.terminal')),
  previous_state text,
  new_state text,
  correlation_key text not null,
  idempotency_key text not null,
  dedupe_key text not null,
  retry_attempt integer not null default 0 check (retry_attempt >= 0),
  rule_version text,
  engine_version text,
  policy_version text,
  entity_type text not null,
  entity_id text not null,
  before_value jsonb,
  proposed_value jsonb,
  applied_value jsonb,
  provider_result_classification text,
  verification_checkpoint text,
  metadata jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  foreign key (action_id, tenant_id) references action(id, tenant_id) on delete restrict,
  unique (tenant_id, action_id, event_type, dedupe_key)
);

create index idx_action_execution_event_tenant_action_at
  on action_execution_event (tenant_id, action_id, occurred_at desc);
create index idx_action_execution_event_tenant_type_at
  on action_execution_event (tenant_id, event_type, occurred_at desc);
create index idx_action_execution_event_tenant_correlation
  on action_execution_event (tenant_id, correlation_key);

alter table action_execution_event enable row level security;
alter table action_execution_event force row level security;
create policy tenant_isolation on action_execution_event
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

revoke all on action_execution_event from axaty_app;
grant select, insert on action_execution_event to axaty_app;

create view v_action_execution_history with (security_invoker = true) as
select id, tenant_id, marketplace_id, account_scope, action_id, actor_type, actor_id,
       event_type, previous_state, new_state, correlation_key, idempotency_key,
       retry_attempt, rule_version, engine_version, policy_version, entity_type,
       entity_id, before_value, proposed_value, applied_value,
       provider_result_classification, verification_checkpoint, metadata, occurred_at
  from action_execution_event;
grant select on v_action_execution_history to axaty_app;
