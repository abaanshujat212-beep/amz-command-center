-- Append-only evidence of Amazon-native campaign optimization controls.
create table campaign_native_control_state (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  campaign_id text not null check (btrim(campaign_id) <> ''),
  bidding_strategy text not null,
  bidding_strategy_supported boolean not null,
  budget_rule_active boolean not null default false,
  schedule_rule_active boolean not null default false,
  rule_based_bidding_active boolean not null default false,
  cost_control_active boolean not null default false,
  source_observed_at timestamptz not null,
  source_api_version text not null check (btrim(source_api_version) <> ''),
  source_fingerprint text not null check (source_fingerprint ~ '^[0-9a-f]{64}$'),
  source_record jsonb not null check (jsonb_typeof(source_record) = 'object'),
  loaded_at timestamptz not null default now(),
  unique (tenant_id, campaign_id, source_api_version, source_fingerprint)
);

create index campaign_native_control_latest_idx
  on campaign_native_control_state (tenant_id, campaign_id, source_observed_at desc, loaded_at desc);

alter table campaign_native_control_state enable row level security;
alter table campaign_native_control_state force row level security;
create policy tenant_isolation on campaign_native_control_state
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

-- Evidence is append-only for the application. Tenant deletion remains available
-- to the owning migration role through the foreign-key cascade.
revoke update, delete, truncate on campaign_native_control_state from axaty_app;
grant select, insert on campaign_native_control_state to axaty_app;
