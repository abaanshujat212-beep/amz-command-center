-- Raw snapshot of existing negative keywords from Amazon Ads.
create table if not exists raw.raw_ads_negative_keywords (
  tenant_id uuid not null references tenant(id) on delete cascade,
  campaign_id text not null,
  ad_group_id text,
  keyword_id text not null,
  keyword_text text not null,
  match_type text not null,
  state text not null,
  loaded_at timestamptz not null default now(),
  primary key (tenant_id, keyword_id, loaded_at)
);

create index if not exists idx_raw_ads_negative_keywords_tenant_loaded
  on raw.raw_ads_negative_keywords (tenant_id, loaded_at desc);
