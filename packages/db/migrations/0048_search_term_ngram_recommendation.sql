-- 0048_search_term_ngram_recommendation.sql
-- Append-only, confidence-gated negative n-gram findings (R07.3). Proposal-side
-- only: nothing here is ever sent to Amazon.

create table search_term_ngram_recommendation (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  run_id uuid not null,
  ngram text not null check (ngram ~ '^[a-z0-9]+( [a-z0-9]+){0,2}$'),
  n smallint not null check (n between 1 and 3),
  decision text not null
    check (decision in ('negative_phrase','manual_review','protected','covered')),
  reasons text[] not null default '{}',
  query_count integer not null check (query_count > 0),
  clicks bigint not null check (clicks >= 0),
  impressions bigint not null check (impressions >= 0),
  cost numeric(18,4) not null check (cost >= 0),
  orders bigint not null check (orders >= 0),
  sales numeric(18,4) not null check (sales >= 0),
  chance_zero_orders numeric check (chance_zero_orders between 0 and 1),
  protection_id uuid,
  contributing_queries jsonb not null check (jsonb_typeof(contributing_queries) = 'array'),
  thresholds jsonb not null,
  lookback_days integer not null check (lookback_days between 1 and 365),
  data_through date not null,
  created_at timestamptz not null default now(),
  unique (tenant_id, run_id, ngram),
  foreign key (protection_id, tenant_id)
    references entity_protection(id, tenant_id) on delete restrict,
  check (decision <> 'negative_phrase' or (cardinality(reasons) = 0 and protection_id is null)),
  check ((decision = 'protected') = (protection_id is not null))
);

create index search_term_ngram_recommendation_latest_idx
  on search_term_ngram_recommendation (tenant_id, created_at desc, decision);

create trigger search_term_ngram_recommendation_immutable
before update on search_term_ngram_recommendation
for each row execute function protect_configuration_version();

alter table search_term_ngram_recommendation enable row level security;
alter table search_term_ngram_recommendation force row level security;
create policy tenant_isolation on search_term_ngram_recommendation
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

grant select, insert on search_term_ngram_recommendation to axaty_app;
