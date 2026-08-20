-- Mart: campaign KPIs. Every metric is defined exactly ONCE, here.
-- Divide-by-zero returns null, never 0 — a keyword with no clicks is unknown,
-- not perfect.

with ads as (

    select * from {{ ref('stg_ads_sp_campaign_daily') }}

),

totals as (

    -- total business sales per tenant per day, for TACoS
    select
        tenant_id,
        report_date,
        sum(ordered_product_sales) as total_ordered_product_sales
    from {{ ref('stg_sales_traffic_asin_daily') }}
    group by 1, 2

)

select
    a.tenant_id,
    a.report_date,
    a.campaign_id,
    a.campaign_name,
    a.campaign_status,
    a.targeting_type,
    a.budget_amount,

    a.impressions,
    a.clicks,
    a.cost,
    a.attributed_orders_7d,
    a.attributed_sales_7d,
    a.attributed_units_7d,

    -- KPIs (null-safe)
    case when a.attributed_sales_7d > 0
         then a.cost / a.attributed_sales_7d end          as acos,
    case when a.cost > 0
         then a.attributed_sales_7d / a.cost end          as roas,
    case when a.impressions > 0
         then a.clicks::numeric / a.impressions end       as ctr,
    case when a.clicks > 0
         then a.attributed_orders_7d::numeric / a.clicks end as cvr,
    case when a.clicks > 0
         then a.cost / a.clicks end                       as cpc,
    case when t.total_ordered_product_sales > 0
         then a.cost / t.total_ordered_product_sales end  as tacos,

    -- settlement flag: rules may only act where this is true
    (a.report_date <= current_date - interval '{{ var("settlement_lag_days") }} days')
        as is_settled

from ads a
left join totals t
    on  a.tenant_id  = t.tenant_id
    and a.report_date = t.report_date
