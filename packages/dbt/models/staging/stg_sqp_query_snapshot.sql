with source as (
    select * from {{ source('raw', 'raw_sqp_query_snapshot') }}
), ranked as (
    select *, row_number() over (partition by tenant_id, asin, search_query, report_date order by loaded_at desc) as _rn
    from source
)
select
    tenant_id::uuid as tenant_id,
    asin::text as asin,
    lower(trim(search_query))::text as search_query,
    report_date::date as report_date,
    coalesce(query_volume, 0)::integer as query_volume,
    coalesce(impressions, 0)::integer as impressions,
    coalesce(clicks, 0)::integer as clicks,
    coalesce(cart_adds, 0)::integer as cart_adds,
    coalesce(purchases, 0)::integer as purchases,
    query_rank,
    loaded_at
from ranked
where _rn = 1
  and search_query is not null
  and trim(search_query) <> ''
