with sqp as (
    select
        tenant_id,
        asin,
        search_query,
        sum(query_volume) as query_volume_30d,
        sum(impressions) as impressions_30d,
        sum(clicks) as clicks_30d,
        sum(cart_adds) as cart_adds_30d,
        sum(purchases) as purchases_30d,
        min(query_rank) as best_query_rank
    from {{ ref('stg_sqp_query_snapshot') }}
    where report_date >= current_date - interval '30 days'
    group by 1, 2, 3
), ads_terms as (
    select
        tenant_id,
        lower(trim(search_term)) as search_query,
        bool_or(exists_as_exact) as exists_as_exact,
        bool_or(is_already_negative) as is_already_negative,
        sum(cost) as ad_spend_30d,
        sum(attributed_sales_7d) as ad_sales_30d
    from {{ ref('mart_ppc_search_term_daily') }}
    where report_date >= current_date - interval '30 days'
    group by 1, 2
), product as (
    select tenant_id, asin, opportunity_score as product_opportunity_score,
           contribution_margin_pct, break_even_acos, economics_incomplete
    from {{ ref('mart_product_opportunity') }}
)
select
    s.tenant_id,
    s.asin,
    s.search_query,
    s.query_volume_30d,
    s.impressions_30d,
    s.clicks_30d,
    s.cart_adds_30d,
    s.purchases_30d,
    s.best_query_rank,
    case when s.impressions_30d > 0 then s.clicks_30d::numeric / s.impressions_30d end as query_ctr,
    case when s.clicks_30d > 0 then s.purchases_30d::numeric / s.clicks_30d end as query_cvr,
    coalesce(a.exists_as_exact, false) as exists_as_exact,
    coalesce(a.is_already_negative, false) as is_already_negative,
    coalesce(a.ad_spend_30d, 0) as ad_spend_30d,
    coalesce(a.ad_sales_30d, 0) as ad_sales_30d,
    case when coalesce(a.ad_sales_30d, 0) > 0 then a.ad_spend_30d / a.ad_sales_30d end as ads_acos,
    p.product_opportunity_score,
    p.contribution_margin_pct,
    p.break_even_acos,
    coalesce(p.economics_incomplete, true) as economics_incomplete,
    (
        case when s.query_volume_30d >= 10000 then 30 when s.query_volume_30d >= 2500 then 20 when s.query_volume_30d >= 500 then 10 else 0 end
      + case when s.best_query_rank is not null and s.best_query_rank <= 10 then 20 when s.best_query_rank is not null and s.best_query_rank <= 50 then 10 else 0 end
      + case when s.clicks_30d > 0 and s.purchases_30d::numeric / s.clicks_30d >= 0.10 then 20 when s.clicks_30d > 0 and s.purchases_30d::numeric / s.clicks_30d >= 0.04 then 10 else 0 end
      + case when not coalesce(a.exists_as_exact, false) then 15 else 0 end
      + case when coalesce(a.ad_spend_30d, 0) = 0 then 10 else 0 end
      + case when coalesce(p.product_opportunity_score, 0) >= 60 then 5 else 0 end
    )::integer as sqp_opportunity_score,
    case
        when coalesce(a.is_already_negative, false) then 'already_negative'
        when not coalesce(a.exists_as_exact, false) and s.purchases_30d > 0 then 'harvest_exact'
        when coalesce(a.ad_spend_30d, 0) = 0 and s.query_volume_30d >= 2500 then 'test_campaign'
        when coalesce(a.ad_sales_30d, 0) = 0 and coalesce(a.ad_spend_30d, 0) > 0 then 'watch_spend'
        else 'monitor'
    end as suggested_action
from sqp s
left join ads_terms a on a.tenant_id = s.tenant_id and a.search_query = s.search_query
left join product p on p.tenant_id = s.tenant_id and p.asin = s.asin
