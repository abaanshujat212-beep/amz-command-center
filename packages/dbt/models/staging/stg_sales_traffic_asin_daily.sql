-- Staging: SP-API Sales & Traffic report at CHILD ASIN granularity.
--
-- This is the denominator for TACoS: total business sales, not just ad sales.
-- It is also where avg_price comes from for unit economics.
--
-- CHILD granularity matters. A parent ASIN rolls up variations that can have
-- different prices and costs, which would silently produce a wrong break-even
-- ACOS for every rule downstream.

with source as (

    select * from {{ source('raw', 'raw_sales_traffic_asin_daily') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by tenant_id, report_date, child_asin
            order by loaded_at desc
        ) as _rn
    from source

)

select
    tenant_id::uuid                             as tenant_id,
    report_date::date                           as report_date,
    child_asin::text                            as asin,
    parent_asin::text                           as parent_asin,
    sku::text                                   as sku,

    coalesce(units_ordered, 0)::bigint           as units_ordered,
    coalesce(ordered_product_sales, 0)::numeric(18,4) as ordered_product_sales,
    coalesce(total_order_items, 0)::bigint       as total_order_items,
    coalesce(sessions, 0)::bigint                as sessions,
    coalesce(page_views, 0)::bigint              as page_views,

    -- Amazon sends these as percentages; normalise to fractions like everywhere
    -- else in the project.
    case when buy_box_percentage is null then null
         else buy_box_percentage::numeric / 100.0 end as buy_box_pct,
    case when unit_session_percentage is null then null
         else unit_session_percentage::numeric / 100.0 end as unit_session_pct,

    -- Average selling price, VAT-inclusive (it is what the customer paid).
    -- mart_sku_economics divides this by (1 + vat_rate) before margin maths.
    case when coalesce(units_ordered, 0) > 0
         then ordered_product_sales::numeric / units_ordered
    end                                          as avg_price_gross,

    loaded_at
from ranked
where _rn = 1
  and child_asin is not null
