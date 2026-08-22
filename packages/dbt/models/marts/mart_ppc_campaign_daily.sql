-- Mart: campaign KPIs. Every metric is defined exactly ONCE, here.
-- Divide-by-zero returns null, never 0 — a keyword with no clicks is unknown,
-- not perfect.
--
-- break_even_acos and budget_utilisation exist here because the rules engine
-- aggregates them for campaign-scope rules. If they are removed or renamed,
-- services/rules/query.py breaks -- keep the two in sync.

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

),

-- Worst-case break-even for the campaign: the thinnest-margin ASIN it
-- advertises. A campaign-level budget increase pushes spend onto ALL of its
-- products, so the most fragile one has to set the limit.
campaign_economics as (

    select
        p.tenant_id,
        p.campaign_id,
        min(e.break_even_acos)          as break_even_acos,
        min(e.contribution_margin_pct)  as contribution_margin_pct,
        bool_or(e.economics_incomplete) as economics_incomplete,
        count(distinct p.asin)          as advertised_asins
    from {{ ref('stg_ads_advertised_product_daily') }} p
    left join {{ ref('mart_sku_economics') }} e
        on  e.tenant_id = p.tenant_id
        and e.asin      = p.asin
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

    -- Share of the daily budget actually spent. A campaign at ~1.0 is being
    -- throttled by budget, which is the signal the scaling rule looks for.
    -- Null (not 0) when there is no budget on record, so 'unknown' can never
    -- look like 'not capped'.
    case when a.budget_amount > 0
         then a.cost / a.budget_amount end                as budget_utilisation,

    g.break_even_acos,
    g.contribution_margin_pct,
    g.economics_incomplete,
    g.advertised_asins,

    -- settlement flag: rules may only act where this is true
    (a.report_date <= current_date - interval '{{ var("settlement_lag_days") }} days')
        as is_settled

from ads a
left join totals t
    on  a.tenant_id  = t.tenant_id
    and a.report_date = t.report_date
left join campaign_economics g
    on  a.tenant_id   = g.tenant_id
    and a.campaign_id = g.campaign_id
