-- Mart: customer search terms. Feeds the negate and harvest rules.
--
-- Two flags do the real work here:
--   is_already_negative -- never propose a negative that already exists
--   exists_as_exact     -- never harvest a term we already bid on exactly
-- Without them the engine would generate the same proposal every single run and
-- the approval queue would become noise nobody reads.

with st as (

    select * from {{ ref('stg_ads_sp_search_term_daily') }}

),

negatives as (

    select distinct
        tenant_id,
        ad_group_id,
        lower(trim(keyword_text)) as term
    from {{ ref('stg_ads_negative_keywords') }}

),

exact_keywords as (

    select distinct
        tenant_id,
        lower(trim(keyword_text)) as term
    from {{ ref('stg_ads_sp_keyword_daily') }}
    where match_type = 'exact'

),

ad_group_economics as (

    select
        p.tenant_id,
        p.ad_group_id,
        min(e.break_even_acos) as break_even_acos
    from {{ ref('stg_ads_advertised_product_daily') }} p
    left join {{ ref('mart_sku_economics') }} e
        on  e.tenant_id = p.tenant_id
        and e.asin      = p.asin
    group by 1, 2

)

select
    s.tenant_id,
    s.report_date,
    s.campaign_id,
    s.ad_group_id,
    s.search_term,
    s.keyword_id            as matched_keyword_id,
    s.keyword_text          as matched_keyword_text,
    s.match_type            as matched_match_type,
    s.bid,

    s.impressions,
    s.clicks,
    s.cost,
    s.attributed_orders_7d,
    s.attributed_sales_7d,
    s.attributed_units_7d,

    case when s.attributed_sales_7d > 0 then s.cost / s.attributed_sales_7d end as acos,
    case when s.impressions > 0 then s.clicks::numeric / s.impressions end      as ctr,
    case when s.clicks > 0 then s.attributed_orders_7d::numeric / s.clicks end  as cvr,
    case when s.clicks > 0 then s.cost / s.clicks end                           as cpc,

    g.break_even_acos,

    (n.term is not null) as is_already_negative,
    (x.term is not null) as exists_as_exact,

    (s.report_date <= current_date - interval '{{ var("settlement_lag_days") }} days')
        as is_settled

from st s
left join negatives n
    on  s.tenant_id   = n.tenant_id
    and s.ad_group_id = n.ad_group_id
    and lower(trim(s.search_term)) = n.term
left join exact_keywords x
    on  s.tenant_id = x.tenant_id
    and lower(trim(s.search_term)) = x.term
left join ad_group_economics g
    on  s.tenant_id   = g.tenant_id
    and s.ad_group_id = g.ad_group_id
