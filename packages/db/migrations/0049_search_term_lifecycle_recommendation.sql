-- 0049_search_term_lifecycle_recommendation.sql
-- R07.4: proposal-only search-term isolation negatives and historical-winner
-- revive recommendations. Nothing here is ever sent to Amazon.

alter table search_term_harvest_lineage
  add constraint search_term_harvest_lineage_id_tenant_key unique (id, tenant_id);

create table search_term_lifecycle_recommendation (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  run_id uuid not null,
  recommendation_type text not null
    check (recommendation_type in ('isolation_negative','revive_target')),
  decision text not null check (decision in ('recommended','blocked')),
  blocked_reason text check (blocked_reason in (
    'unsupported_match_type','same_ad_group','duplicate','already_negative','protected',
    'destination_missing','destination_inactive','destination_no_traffic','source_no_traffic',
    'recent_traffic','thin_history','economics_unknown','poor_history','bid_unknown',
    'bounds','cooldown')),
  subject_key text not null check (btrim(subject_key) <> ''),
  campaign_id text not null,
  ad_group_id text not null,
  keyword_id text,
  term text not null,
  match_type text not null,
  lineage_id uuid,
  protection_id uuid,
  current_bid numeric(12,2) check (current_bid is null or current_bid >= 0),
  proposed_bid numeric(12,2) check (proposed_bid is null or proposed_bid > 0),
  evidence jsonb not null check (jsonb_typeof(evidence) = 'object'),
  thresholds jsonb not null check (jsonb_typeof(thresholds) = 'object'),
  data_through date not null,
  created_at timestamptz not null default now(),
  unique (tenant_id, run_id, recommendation_type, subject_key),
  foreign key (lineage_id, tenant_id) references search_term_harvest_lineage(id, tenant_id),
  foreign key (protection_id, tenant_id) references entity_protection(id, tenant_id),
  check ((decision = 'recommended') = (blocked_reason is null)),
  check ((coalesce(blocked_reason, '') = 'protected') = (protection_id is not null)),
  check (recommendation_type <> 'isolation_negative'
         or (lineage_id is not null and match_type = 'negative_exact' and proposed_bid is null)),
  check (recommendation_type <> 'revive_target'
         or (keyword_id is not null and lineage_id is null
             and (decision = 'blocked') = (proposed_bid is null)))
);

create index search_term_lifecycle_recommendation_latest_idx
  on search_term_lifecycle_recommendation (tenant_id, created_at desc, recommendation_type);

-- at most one recommended isolation negative per source ad group and term per run
create unique index search_term_lifecycle_recommendation_one_isolation_idx
  on search_term_lifecycle_recommendation (tenant_id, run_id, campaign_id, ad_group_id, term)
  where recommendation_type = 'isolation_negative' and decision = 'recommended';

create trigger search_term_lifecycle_recommendation_immutable
before update on search_term_lifecycle_recommendation
for each row execute function protect_configuration_version();

alter table search_term_lifecycle_recommendation enable row level security;
alter table search_term_lifecycle_recommendation force row level security;
create policy tenant_isolation on search_term_lifecycle_recommendation
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

grant select, insert on search_term_lifecycle_recommendation to axaty_app;
