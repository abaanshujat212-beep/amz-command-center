-- 0011_ads_raw_tables.sql
-- Raw landing tables for first-pass Amazon Ads daily reports.

create schema if not exists raw;

do $$
declare
  table_name text;
  table_names text[] := array[
    'raw_ads_sp_campaign_daily',
    'raw_ads_sp_placement_daily',
    'raw_ads_sp_ad_group_daily',
    'raw_ads_sp_keyword_daily',
    'raw_ads_sp_search_term_daily',
    'raw_ads_advertised_product_daily',
    'raw_ads_sp_purchased_product_daily'
  ];
begin
  foreach table_name in array table_names loop
    execute format($sql$
      create table if not exists raw.%I (
        tenant_id uuid not null references public.tenant(id) on delete cascade,
        report_date date not null,
        entity_id text not null,
        record jsonb not null,
        loaded_at timestamptz not null default now(),
        primary key (tenant_id, report_date, entity_id)
      )
    $sql$, table_name);

    execute format(
      'create index if not exists %I on raw.%I (tenant_id, loaded_at desc)',
      'idx_' || table_name || '_tenant_loaded',
      table_name
    );
  end loop;
end $$;

grant usage on schema raw to axaty_app;
grant select, insert, update, delete on all tables in schema raw to axaty_app;
