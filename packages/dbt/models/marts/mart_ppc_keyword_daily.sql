-- Mart: keyword/target level KPIs joined to unit economics.
-- This is the table the rules engine reads for scope = 'keyword'.
--
-- break_even_acos comes from mart_sku_economics via the advertised ASIN. If a
-- keyword advertises several ASINs we take the WORST (lowest) break-even, so a
-- rule can never be more aggressive than the thinnest-margin product it sells.

with kw as (

    select * from {{ ref('stg_ads_sp_keyword_daily') }}

),

economics as (

    select
        tenant_id,
        asin,
        break_even_acos,
        contribution_margin_pct,
        economics_incomplete
    from {{ ref('mart_sku_economics') }}

),

-- worst-case break-even per ad group
ad_group_economics as (

    select
        p.tenant_id,
        p.ad_group_id,
        min(e.break_even_acos)                     as break_even_acos,
        min(e.contribution_margin_pct)             as contribution_margin_pct,
        bool_or(e.economics_incomplete)            as economics_incomplete,
        count(distinct p.asin)                     as advertised_asins
    from {{ ref('stg_ads_advertised_product_daily') }} p
    left join economics e
        on  e.tenant_id = p.tenant_id
        and e.asin      = p.asin
    group by 1, 2

),

account_cvr as (

    select
        tenant_id,
        report_date,
        case when sum(clicks) > 0
             then sum(attributed_orders_7d)::numeric / sum(clicks) end as account_cvr
    from kw
    group by 1, 2

)

select
    k.tenant_id,
    k.report_date,
    k.campaign_id,
    k.campaign_name,
    k.ad_group_id,
    k.keyword_id,
    k.keyword_text,
    k.match_type,
    k.keyword_status,
    k.bid,

    k.impressions,
    k.clicks,
    k.cost,
    k.attributed_orders_7d,
    k.attributed_sales_7d,
    k.attributed_units_7d,
    k.top_of_search_impression_share,

    g.advertised_asins,
    ae.asin,

    -- KPIs, null-safe
    case when k.attributed_sales_7d > 0 then k.cost / k.attributed_sales_7d end as acos,
    case when k.cost > 0 then k.attributed_sales_7d / k.cost end                as roas,
    case when k.impressions > 0 then k.clicks::numeric / k.impressions end      as ctr,
    case when k.clicks > 0 then k.attributed_orders_7d::numeric / k.clicks end  as cvr,
    case when k.clicks > 0 then k.cost / k.clicks end                           as cpc,

    g.break_even_acos,
    g.contribution_margin_pct,
    g.economics_incomplete,
    a.account_cvr,

    -- profitability verdict, relative to break-even and never to a fixed number
    case
        when g.break_even_acos is null then 'unknown'
        when k.attributed_sales_7d = 0 and k.clicks > 0 then 'no_sales'
        when k.attributed_sales_7d = 0 then 'no_data'
        when (k.cost / k.attributed_sales_7d) <= g.break_even_acos * 0.7 then 'strong'
        when (k.cost / k.attributed_sales_7d) <= g.break_even_acos then 'profitable'
        when (k.cost / k.attributed_sales_7d) <= g.break_even_acos * 1.3 then 'marginal'
        else 'losing'
    end as verdict,

    (k.report_date <= current_date - interval '{{ var("settlement_lag_days") }} days')
        as is_settled

from kw k
left join ad_group_economics g
    on  k.tenant_id   = g.tenant_id
    and k.ad_group_id = g.ad_group_id
left join account_cvr a
    on  k.tenant_id   = a.tenant_id
    and k.report_date = a.report_date
left join lateral (
    select p.asin
    from {{ ref('stg_ads_advertised_product_daily') }} p
    where p.tenant_id = k.tenant_id
      and p.ad_group_id = k.ad_group_id
    order by p.attributed_sales_7d desc nulls last
    limit 1
) ae on true
