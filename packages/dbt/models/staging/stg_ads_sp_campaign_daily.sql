-- Staging: Sponsored Products campaign report.
-- Rename, cast, deduplicate. No metrics here — KPIs live in marts.

with source as (

    select * from {{ source('raw', 'raw_ads_sp_campaign_daily') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by tenant_id, report_date, campaign_id
            order by loaded_at desc
        ) as _rn
    from source

)

select
    tenant_id::uuid                       as tenant_id,
    report_date::date                     as report_date,
    campaign_id::text                     as campaign_id,
    campaign_name::text                   as campaign_name,
    campaign_status::text                 as campaign_status,
    targeting_type::text                  as targeting_type,
    coalesce(impressions, 0)::bigint      as impressions,
    coalesce(clicks, 0)::bigint           as clicks,
    coalesce(cost, 0)::numeric(18,4)      as cost,
    coalesce(purchases_7d, 0)::bigint     as attributed_orders_7d,
    coalesce(sales_7d, 0)::numeric(18,4)  as attributed_sales_7d,
    coalesce(units_sold_clicks_7d, 0)::bigint as attributed_units_7d,
    campaign_budget_amount::numeric(12,2) as budget_amount,
    campaign_budget_type::text            as budget_type,
    loaded_at
from ranked
where _rn = 1
