with source as (
    select * from {{ source('raw', 'raw_sales_traffic_asin_daily') }}
), ranked as (
    select *, row_number() over (partition by tenant_id, report_date, entity_id order by loaded_at desc) as _rn
    from source
)
select
    tenant_id::uuid as tenant_id,
    report_date::date as report_date,
    coalesce(record->>'child_asin', record->>'childAsin', record->>'asin', entity_id)::text as asin,
    coalesce(record->>'parent_asin', record->>'parentAsin')::text as parent_asin,
    coalesce(record->>'sku', record->>'sellerSku')::text as sku,
    coalesce((coalesce(record->>'units_ordered', record->>'unitsOrdered'))::bigint, 0) as units_ordered,
    coalesce((coalesce(record->>'ordered_product_sales', record->>'orderedProductSales'))::numeric(18,4), 0) as ordered_product_sales,
    coalesce((coalesce(record->>'total_order_items', record->>'totalOrderItems'))::bigint, 0) as total_order_items,
    coalesce((record->>'sessions')::bigint, 0) as sessions,
    coalesce((coalesce(record->>'page_views', record->>'pageViews'))::bigint, 0) as page_views,
    case when coalesce(record->>'buy_box_percentage', record->>'buyBoxPercentage') is null then null
         else (coalesce(record->>'buy_box_percentage', record->>'buyBoxPercentage'))::numeric / 100.0 end as buy_box_pct,
    case when coalesce(record->>'unit_session_percentage', record->>'unitSessionPercentage') is null then null
         else (coalesce(record->>'unit_session_percentage', record->>'unitSessionPercentage'))::numeric / 100.0 end as unit_session_pct,
    case when coalesce((coalesce(record->>'units_ordered', record->>'unitsOrdered'))::bigint, 0) > 0
         then (coalesce(record->>'ordered_product_sales', record->>'orderedProductSales'))::numeric
              / (coalesce(record->>'units_ordered', record->>'unitsOrdered'))::numeric
    end as avg_price_gross,
    loaded_at
from ranked
where _rn = 1
  and coalesce(record->>'child_asin', record->>'childAsin', record->>'asin', entity_id) is not null
