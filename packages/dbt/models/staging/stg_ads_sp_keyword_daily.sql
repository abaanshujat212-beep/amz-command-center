-- Staging: Sponsored Products keyword/target report.
--
-- This is the busiest table in the project: the keyword mart, the search-term
-- mart (for exists_as_exact) and most rules all read from it.
--
-- top_of_search_impression_share is kept here because the impression-starved
-- rule needs it, and it only arrives on the keyword report -- not on campaign.

with source as (

    select * from {{ source('raw', 'raw_ads_sp_keyword_daily') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by tenant_id, report_date, keyword_id
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
    lower(match_type)::text                    as match_type,
    keyword_status::text                       as keyword_status,

    -- The bid is current configuration, not a historical fact. It is the value
    -- a bid change is applied against, so it must never be coalesced to 0.
    keyword_bid::numeric(12,2)                 as bid,

    coalesce(impressions, 0)::bigint           as impressions,
    coalesce(clicks, 0)::bigint                as clicks,
    coalesce(cost, 0)::numeric(18,4)           as cost,
    coalesce(purchases_7d, 0)::bigint          as attributed_orders_7d,
    coalesce(sales_7d, 0)::numeric(18,4)       as attributed_sales_7d,
    coalesce(units_sold_clicks_7d, 0)::bigint  as attributed_units_7d,

    -- Amazon reports this as a percentage (0-100); rules compare against
    -- fractions, so normalise once, here.
    case
        when top_of_search_impression_share is null then null
        else (top_of_search_impression_share::numeric / 100.0)
    end                                        as top_of_search_impression_share,

    loaded_at
from ranked
where _rn = 1
