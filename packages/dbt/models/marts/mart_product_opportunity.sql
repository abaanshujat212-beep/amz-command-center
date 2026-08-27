with traffic as (
    select
        tenant_id,
        asin,
        min(sku) as sku,
        sum(units_ordered) as units_30d,
        sum(ordered_product_sales) as sales_30d,
        sum(sessions) as sessions_30d,
        sum(page_views) as page_views_30d,
        avg(unit_session_pct) as avg_unit_session_pct
    from {{ ref('stg_sales_traffic_asin_daily') }}
    where report_date >= current_date - interval '30 days'
    group by 1, 2
), ads as (
    select
        tenant_id,
        asin,
        sum(cost) as ad_spend_30d,
        sum(attributed_sales_7d) as ad_sales_30d
    from {{ ref('stg_ads_advertised_product_daily') }}
    where report_date >= current_date - interval '30 days'
    group by 1, 2
), econ as (
    select tenant_id, asin, min(contribution_margin_pct) as contribution_margin_pct,
           min(break_even_acos) as break_even_acos,
           bool_or(economics_incomplete) as economics_incomplete
    from {{ ref('mart_sku_economics') }}
    group by 1, 2
), keepa as (
    select * from {{ ref('stg_keepa_product_snapshot') }}
)
select
    coalesce(t.tenant_id, a.tenant_id, k.tenant_id) as tenant_id,
    coalesce(t.asin, a.asin, k.asin) as asin,
    t.sku,
    k.title,
    k.brand,
    k.buy_box_price,
    k.sales_rank,
    k.review_count,
    k.rating,
    k.offer_count,
    coalesce(t.units_30d, 0) as units_30d,
    coalesce(t.sales_30d, 0) as sales_30d,
    coalesce(t.sessions_30d, 0) as sessions_30d,
    coalesce(a.ad_spend_30d, 0) as ad_spend_30d,
    coalesce(a.ad_sales_30d, 0) as ad_sales_30d,
    case when coalesce(t.sales_30d, 0) > 0 then coalesce(a.ad_spend_30d, 0) / t.sales_30d end as tacos,
    e.contribution_margin_pct,
    e.break_even_acos,
    coalesce(e.economics_incomplete, true) as economics_incomplete,
    (
        case when coalesce(t.sales_30d, 0) >= 1000 then 25 when coalesce(t.sales_30d, 0) >= 250 then 15 else 5 end
      + case when k.sales_rank is not null and k.sales_rank <= 50000 then 20 when k.sales_rank is not null and k.sales_rank <= 150000 then 10 else 0 end
      + case when e.contribution_margin_pct is not null and e.contribution_margin_pct >= 0.30 then 25 when e.contribution_margin_pct is not null and e.contribution_margin_pct >= 0.15 then 12 else 0 end
      + case when k.offer_count is not null and k.offer_count <= 3 then 15 when k.offer_count is not null and k.offer_count <= 8 then 8 else 0 end
      + case when k.rating is not null and k.rating >= 4.2 then 10 when k.rating is not null and k.rating >= 3.8 then 5 else 0 end
      + case when coalesce(t.sessions_30d, 0) > 0 and coalesce(t.units_30d, 0)::numeric / nullif(t.sessions_30d, 0) >= 0.10 then 5 else 0 end
    )::integer as opportunity_score,
    k.captured_at as keepa_captured_at
from traffic t
full join ads a on a.tenant_id = t.tenant_id and a.asin = t.asin
full join keepa k on k.tenant_id = coalesce(t.tenant_id, a.tenant_id) and k.asin = coalesce(t.asin, a.asin)
left join econ e on e.tenant_id = coalesce(t.tenant_id, a.tenant_id, k.tenant_id) and e.asin = coalesce(t.asin, a.asin, k.asin)
