-- Raw Search Query Performance-style query snapshots.
create table if not exists raw.raw_sqp_query_snapshot (
  tenant_id uuid not null references tenant(id) on delete cascade,
  asin text not null,
  search_query text not null,
  report_date date not null,
  query_volume integer,
  impressions integer,
  clicks integer,
  cart_adds integer,
  purchases integer,
  query_rank integer,
  record jsonb not null default '{}'::jsonb,
  loaded_at timestamptz not null default now(),
  primary key (tenant_id, asin, search_query, report_date)
);

create index if not exists idx_raw_sqp_query_snapshot_tenant_query
  on raw.raw_sqp_query_snapshot (tenant_id, search_query, report_date desc);
