-- 0027_tenant_guardrail_settings.sql
-- Persist every guardrail currently enforced by TenantGuardConfig.
-- Defaults remain conservative: automation stays off and dry-run stays on.

alter table tenant_settings
  add column if not exists max_change_pct numeric(6,4) not null default 0.25,
  add column if not exists cooldown_days integer not null default 3,
  add column if not exists max_budget_increase_per_day numeric(12,2) not null default 50.00,
  add column if not exists blast_radius_pct numeric(6,4) not null default 0.30,
  add column if not exists max_data_age_hours integer not null default 48,
  add column if not exists settlement_lag_days integer not null default 3;

alter table tenant_settings
  add constraint tenant_settings_bid_range_valid
    check (min_bid >= 0 and max_bid >= min_bid),
  add constraint tenant_settings_daily_budget_nonnegative
    check (max_daily_budget >= 0),
  add constraint tenant_settings_daily_changes_nonnegative
    check (max_changes_per_day >= 0),
  add constraint tenant_settings_max_change_pct_valid
    check (max_change_pct > 0 and max_change_pct <= 1),
  add constraint tenant_settings_cooldown_days_valid
    check (cooldown_days between 0 and 90),
  add constraint tenant_settings_budget_increase_nonnegative
    check (max_budget_increase_per_day >= 0),
  add constraint tenant_settings_blast_radius_pct_valid
    check (blast_radius_pct > 0 and blast_radius_pct <= 1),
  add constraint tenant_settings_max_data_age_hours_valid
    check (max_data_age_hours between 1 and 720),
  add constraint tenant_settings_settlement_lag_days_valid
    check (settlement_lag_days between 0 and 30);
