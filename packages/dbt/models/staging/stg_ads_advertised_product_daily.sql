-- Staging: advertised product report -- the bridge between Ads and economics.
--
-- This model is what lets us attach a break-even ACOS to a keyword. Ads reports
-- talk about campaigns and keywords; margin lives on ASINs and SKUs. This is
-- the only place the two meet.
--
-- CHILD ASIN granularity is required. A parent ASIN aggregates variations with
-- different costs and prices, which would produce a confidently wrong
-- break-even number.

with source as (

    select * from {{ source('raw', 'raw_ads_advertised_product_daily') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by tenant_id, report_date, ad_group_id, advertised_asin
            order by loaded_at desc
        ) as _rn
    from source

)

select
    tenant_id::uuid                            as tenant_id,
    report_date::date                          as report_date,
    campaign_id::text                          as campaign_id,
    ad_group_id::text                          as ad_group_id,
    advertised_asin::text                      as asin,
    advertised_sku::text                       as sku,
    coalesce(impressions, 0)::bigint           as impressions,
    coalesce(clicks, 0)::bigint                as clicks,
    coalesce(cost, 0)::numeric(18,4)           as cost,
    coalesce(purchases_7d, 0)::bigint          as attributed_orders_7d,
    coalesce(sales_7d, 0)::numeric(18,4)       as attributed_sales_7d,
    coalesce(units_sold_clicks_7d, 0)::bigint  as attributed_units_7d,
    loaded_at
from ranked
where _rn = 1
  and advertised_asin is not null
