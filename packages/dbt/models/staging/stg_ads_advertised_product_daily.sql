with source as (
    select * from {{ source('raw', 'raw_ads_advertised_product_daily') }}
), ranked as (
    select *, row_number() over (partition by tenant_id, report_date, entity_id order by loaded_at desc) as _rn
    from source
)
select
    tenant_id::uuid as tenant_id,
    report_date::date as report_date,
    coalesce(record->>'campaignId', record->>'campaign_id')::text as campaign_id,
    coalesce(record->>'adGroupId', record->>'ad_group_id')::text as ad_group_id,
    coalesce(record->>'advertisedAsin', record->>'advertised_asin', record->>'asin')::text as asin,
    coalesce(record->>'advertisedSku', record->>'advertised_sku', record->>'sku')::text as sku,
    coalesce((record->>'impressions')::bigint, 0) as impressions,
    coalesce((record->>'clicks')::bigint, 0) as clicks,
    coalesce((record->>'cost')::numeric(18,4), 0) as cost,
    coalesce((coalesce(record->>'purchases7d', record->>'purchases_7d'))::bigint, 0) as attributed_orders_7d,
    coalesce((coalesce(record->>'sales7d', record->>'sales_7d'))::numeric(18,4), 0) as attributed_sales_7d,
    coalesce((coalesce(record->>'unitsSoldClicks7d', record->>'units_sold_clicks_7d'))::bigint, 0) as attributed_units_7d,
    loaded_at
from ranked
where _rn = 1
  and coalesce(record->>'advertisedAsin', record->>'advertised_asin', record->>'asin') is not null
