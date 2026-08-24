-- 0012_sales_traffic_raw_table.sql
-- Raw landing table for SP-API Sales & Traffic CHILD ASIN daily report.

create schema if not exists raw;

create table if not exists raw.raw_sales_traffic_asin_daily (
  tenant_id uuid not null references public.tenant(id) on delete cascade,
  report_date date not null,
  entity_id text not null,
  record jsonb not null,
  loaded_at timestamptz not null default now(),
  primary key (tenant_id, report_date, entity_id)
);

create index if not exists idx_raw_sales_traffic_asin_daily_tenant_loaded
  on raw.raw_sales_traffic_asin_daily (tenant_id, loaded_at desc);

grant usage on schema raw to axaty_app;
grant select, insert, update, delete on raw.raw_sales_traffic_asin_daily to axaty_app;
