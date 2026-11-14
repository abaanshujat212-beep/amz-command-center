-- One tenant/day commerce sales total, on the same source and settlement
-- basis used by mart_ppc_campaign_daily for its TACoS denominator.
with sales as (
    select
        tenant_id,
        report_date,
        sum(ordered_product_sales) as total_sales
    from {{ ref('stg_sales_traffic_asin_daily') }}
    group by 1, 2
)
select
    tenant_id,
    report_date,
    total_sales,
    (report_date <= current_date - interval '{{ var("settlement_lag_days") }} days') as is_settled
from sales
