-- Staging: Sponsored Products search term report.
--
-- The grain includes the matched keyword: the same customer search term can be
-- served by several keywords, and collapsing them would hide which keyword is
-- actually wasting the money.

with source as (

    select * from {{ source('raw', 'raw_ads_sp_search_term_daily') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by tenant_id, report_date, campaign_id, ad_group_id,
                         search_term, keyword_id
            order by loaded_at desc
        ) as _rn
    from source

)

select
    tenant_id::uuid                            as tenant_id,
    report_date::date                          as report_date,
    campaign_id::text                          as campaign_id,
    campaign_name::text                        as campaign_name,
    ad_group_id::text                          as ad_group_id,
    keyword_id::text                           as keyword_id,
    keyword_text::text                         as keyword_text,
    lower(trim(search_term))::text             as search_term,
    match_type::text                           as match_type,
    keyword_bid::numeric(12,4)                 as bid,
    coalesce(impressions, 0)::bigint           as impressions,
    coalesce(clicks, 0)::bigint                as clicks,
    coalesce(cost, 0)::numeric(18,4)           as cost,
    coalesce(purchases_7d, 0)::bigint          as attributed_orders_7d,
    coalesce(sales_7d, 0)::numeric(18,4)       as attributed_sales_7d,
    coalesce(units_sold_clicks_7d, 0)::bigint  as attributed_units_7d,
    loaded_at
from ranked
where _rn = 1
  -- Amazon masks low-volume terms; they carry no decision value.
  and search_term is not null
  and search_term not in ('', '*', 'n/a')
