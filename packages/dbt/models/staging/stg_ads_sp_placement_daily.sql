-- Staging: Sponsored Products campaign report, segmented by placement.
--
-- This is the SAME Amazon report as stg_ads_sp_campaign_daily, requested with
-- a placement groupBy. That means the same campaign-day exists at two grains in
-- raw. Never union or join them additively: placements partition the campaign,
-- so summing both grains double-counts spend and halves every ACOS.

with source as (

    select * from {{ source('raw', 'raw_ads_sp_placement_daily') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by tenant_id, report_date, campaign_id, placement_classification
            order by loaded_at desc
        ) as _rn
    from source

)

select
    tenant_id::uuid                           as tenant_id,
    report_date::date                         as report_date,
    campaign_id::text                         as campaign_id,
    campaign_name::text                       as campaign_name,
    campaign_status::text                     as campaign_status,
    placement_classification::text            as placement_raw,

    -- Canonical placement code. Amazon has spelled these at least two ways
    -- ('TOP_OF_SEARCH' in reporting v3, 'Top of Search on-Amazon' in older v2
    -- exports) and a rule must not care which era a row came from.
    case upper(trim(placement_classification))
        when 'TOP_OF_SEARCH'           then 'top_of_search'
        when 'TOP OF SEARCH ON-AMAZON' then 'top_of_search'
        when 'DETAIL_PAGE'             then 'product_page'
        when 'DETAIL PAGE ON-AMAZON'   then 'product_page'
        when 'OTHER_ON_AMAZON'         then 'rest_of_search'
        when 'OTHER ON-AMAZON'         then 'rest_of_search'
        when 'OFF_AMAZON'              then 'off_amazon'
        when 'OFF AMAZON'              then 'off_amazon'
        else 'unknown'
    end as placement,

    -- The enum the Ads API expects when writing a placement bid adjustment.
    -- NULL means "this placement cannot take a modifier": off-Amazon has no
    -- multiplier at all, and an unrecognised value must never be guessed into
    -- one -- guessing here would send a real bid change to the wrong slot.
    case upper(trim(placement_classification))
        when 'TOP_OF_SEARCH'           then 'PLACEMENT_TOP'
        when 'TOP OF SEARCH ON-AMAZON' then 'PLACEMENT_TOP'
        when 'DETAIL_PAGE'             then 'PLACEMENT_PRODUCT_PAGE'
        when 'DETAIL PAGE ON-AMAZON'   then 'PLACEMENT_PRODUCT_PAGE'
        when 'OTHER_ON_AMAZON'         then 'PLACEMENT_REST_OF_SEARCH'
        when 'OTHER ON-AMAZON'         then 'PLACEMENT_REST_OF_SEARCH'
    end as placement_api_enum,

    coalesce(impressions, 0)::bigint          as impressions,
    coalesce(clicks, 0)::bigint               as clicks,
    coalesce(cost, 0)::numeric(18,4)          as cost,
    coalesce(purchases_7d, 0)::bigint         as attributed_orders_7d,
    coalesce(sales_7d, 0)::numeric(18,4)      as attributed_sales_7d,
    coalesce(units_sold_clicks_7d, 0)::bigint as attributed_units_7d,
    loaded_at
from ranked
where _rn = 1
