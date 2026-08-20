-- 0003_rules_actions.sql
-- Rules engine, action state machine, per-SKU economics and alerts.
--
-- Design rules encoded here:
--   * rules are DATA (jsonb), never code -- adding a rule needs no deploy
--   * every evaluation stores the metric snapshot that caused it
--   * actions move through an explicit state machine, nothing skips approval
--   * before_value is captured from Amazon at apply time, not from our marts

-- ------------------------------------------------------------------ rules
create table if not exists rule (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenant(id) on delete cascade,
  code            text not null,
  name            text not null,
  description     text,
  enabled         boolean not null default false,
  dry_run         boolean not null default true,
  priority        integer not null default 100,
  scope           text not null
                  check (scope in ('campaign','ad_group','keyword','target',
                                   'search_term','placement','asin')),
  condition_jsonb jsonb not null,
  action_jsonb    jsonb not null,
  lookback_days   integer not null default 14,
  min_clicks      integer not null default 15,
  min_impressions integer not null default 500,
  created_by      uuid,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (tenant_id, code)
);

create index if not exists idx_rule_tenant_enabled
  on rule (tenant_id, enabled, priority);

create table if not exists rule_evaluation (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenant(id) on delete cascade,
  rule_id          uuid not null references rule(id) on delete cascade,
  run_id           uuid not null,
  entity_type      text not null,
  entity_id        text not null,
  data_through     date not null,
  evaluated_at     timestamptz not null default now(),
  matched          boolean not null,
  metrics_snapshot jsonb not null,
  proposed_action  jsonb,
  reason_text      text,
  blocked_by       text
);

create index if not exists idx_rule_evaluation_tenant_run
  on rule_evaluation (tenant_id, run_id);
create index if not exists idx_rule_evaluation_tenant_entity
  on rule_evaluation (tenant_id, entity_type, entity_id, evaluated_at desc);

-- ---------------------------------------------------------------- actions
-- pending -> approved -> applied -> verified
--         -> rejected | expired | failed | rolled_back
create table if not exists action (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenant(id) on delete cascade,
  rule_id         uuid references rule(id) on delete set null,
  evaluation_id   uuid references rule_evaluation(id) on delete set null,
  entity_type     text not null,
  entity_id       text not null,
  action_type     text not null
                  check (action_type in ('set_bid','set_budget','pause','enable',
                                         'add_negative_exact','add_negative_phrase',
                                         'create_keyword','set_placement_modifier')),
  before_value    jsonb,
  after_value     jsonb not null,
  status          text not null default 'pending'
                  check (status in ('pending','approved','applied','verified',
                                    'rejected','expired','failed','rolled_back')),
  reason_text     text,
  clamped         boolean not null default false,
  clamp_note      text,
  idempotency_key text not null,
  requested_at    timestamptz not null default now(),
  expires_at      timestamptz not null default now() + interval '48 hours',
  approved_by     uuid,
  approved_at     timestamptz,
  applied_at      timestamptz,
  verified_at     timestamptz,
  rolled_back_at  timestamptz,
  outcome         text check (outcome in ('improved','worsened','neutral',
                                          'inconclusive','drifted')),
  impact_jsonb    jsonb,
  api_response    jsonb,
  error           text,
  unique (tenant_id, idempotency_key)
);

create index if not exists idx_action_tenant_status
  on action (tenant_id, status, requested_at desc);
create index if not exists idx_action_tenant_entity_applied
  on action (tenant_id, entity_type, entity_id, applied_at desc);

-- Cooldown lookup: last applied change per entity.
create or replace view v_last_applied_action as
select tenant_id, entity_type, entity_id, max(applied_at) as last_applied_at
from action
where status in ('applied','verified')
group by 1, 2, 3;

-- -------------------------------------------------------------- economics
-- Time-versioned so historical margins stay correct when costs change.
create table if not exists sku_cost_ledger (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenant(id) on delete cascade,
  sku                  text not null,
  asin                 text,
  valid_from           date not null,
  valid_to             date,
  cogs                 numeric(12,4) not null,
  freight_in           numeric(12,4) not null default 0,
  amazon_referral_pct  numeric(6,4)  not null default 0.15,
  fba_fee              numeric(12,4) not null default 0,
  storage_est          numeric(12,4) not null default 0,
  vat_rate             numeric(6,4)  not null default 0.20,
  currency             text not null default 'GBP',
  note                 text,
  created_at           timestamptz not null default now(),
  check (valid_to is null or valid_to > valid_from)
);

create index if not exists idx_sku_cost_tenant_sku
  on sku_cost_ledger (tenant_id, sku, valid_from desc);

-- No overlapping validity windows for the same SKU.
create unique index if not exists uq_sku_cost_open_window
  on sku_cost_ledger (tenant_id, sku)
  where valid_to is null;

-- ----------------------------------------------------------------- alerts
create table if not exists alert (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenant(id) on delete cascade,
  kind         text not null
               check (kind in ('auth_expiring','auth_expired','pipeline_failed',
                               'data_stale','blast_radius_halt','budget_guard',
                               'action_failed','economics_incomplete')),
  severity     text not null default 'warning'
               check (severity in ('info','warning','critical')),
  title        text not null,
  detail       jsonb,
  entity_ref   text,
  created_at   timestamptz not null default now(),
  acknowledged_by uuid,
  acknowledged_at timestamptz,
  resolved_at  timestamptz
);

create index if not exists idx_alert_tenant_open
  on alert (tenant_id, created_at desc)
  where resolved_at is null;

-- Daily change budget lookup (guardrail: max_changes_per_day).
create or replace view v_changes_today as
select tenant_id, count(*) as applied_today,
       coalesce(sum((after_value->>'budget')::numeric
                  - (before_value->>'budget')::numeric), 0) as budget_delta_today
from action
where status in ('applied','verified')
  and applied_at >= date_trunc('day', now())
group by 1;

-- -------------------------------------------------------------------- RLS
do $$
declare
  t text;
  tenant_tables text[] := array[
    'rule', 'rule_evaluation', 'action', 'sku_cost_ledger', 'alert'
  ];
begin
  foreach t in array tenant_tables loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force  row level security', t);
    execute format('drop policy if exists tenant_isolation on %I', t);
    execute format($f$
      create policy tenant_isolation on %I
        using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    $f$, t);
  end loop;
end $$;

grant select, insert, update, delete on all tables in schema public to axaty_app;
grant select on v_last_applied_action, v_changes_today to axaty_app;
