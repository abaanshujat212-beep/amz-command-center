-- Raw snapshot of current campaign placement bidding modifiers.
create table if not exists raw.raw_ads_placement_config (
  tenant_id uuid not null references tenant(id) on delete cascade,
  campaign_id text not null,
  placement text not null,
  percentage numeric(8,2) not null default 0,
  loaded_at timestamptz not null default now(),
  record jsonb not null default '{}'::jsonb,
  primary key (tenant_id, campaign_id, placement, loaded_at)
);

create index if not exists idx_raw_ads_placement_config_latest
  on raw.raw_ads_placement_config (tenant_id, campaign_id, loaded_at desc);
