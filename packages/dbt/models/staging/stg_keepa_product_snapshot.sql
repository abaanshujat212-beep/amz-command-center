with source as (
    select * from {{ source('raw', 'raw_keepa_product_snapshot') }}
), ranked as (
    select *, row_number() over (partition by tenant_id, asin order by captured_at desc) as _rn
    from source
)
select
    tenant_id::uuid as tenant_id,
    asin::text as asin,
    title,
    brand,
    buy_box_price,
    sales_rank,
    review_count,
    rating,
    offer_count,
    captured_at
from ranked
where _rn = 1
