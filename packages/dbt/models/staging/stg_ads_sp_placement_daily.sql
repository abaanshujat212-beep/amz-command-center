with source as (
    select * from {{ source('raw', 'raw_ads_sp_placement_daily') }}
), ranked as (
    select *, row_number() over (partition by tenant_id, report_date, entity_id order by loaded_at desc) as _rn
    from source
)
select
    tenant_id::uuid as tenant_id,
    report_date::date as report_date,
    coalesce(record->>'campaignId', record->>'campaign_id')::text as campaign_id,
    coalesce(record->>'campaignName', record->>'campaign_name')::text as campaign_name,
    coalesce(record->>'campaignStatus', record->>'campaign_status')::text as campaign_status,
    coalesce(record->>'placementClassification', record->>'placement_classification')::text as placement_raw,
    case upper(trim(coalesce(record->>'placementClassification', record->>'placement_classification')))
        when 'TOP_OF_SEARCH' then 'top_of_search'
        when 'TOP OF SEARCH ON-AMAZON' then 'top_of_search'
        when 'DETAIL_PAGE' then 'product_page'
        when 'DETAIL PAGE ON-AMAZON' then 'product_page'
        when 'OTHER_ON_AMAZON' then 'rest_of_search'
        when 'OTHER ON-AMAZON' then 'rest_of_search'
        when 'OFF_AMAZON' then 'off_amazon'
        when 'OFF AMAZON' then 'off_amazon'
        else 'unknown'
    end as placement,
    case upper(trim(coalesce(record->>'placementClassification', record->>'placement_classification')))
        when 'TOP_OF_SEARCH' then 'PLACEMENT_TOP'
        when 'TOP OF SEARCH ON-AMAZON' then 'PLACEMENT_TOP'
        when 'DETAIL_PAGE' then 'PLACEMENT_PRODUCT_PAGE'
        when 'DETAIL PAGE ON-AMAZON' then 'PLACEMENT_PRODUCT_PAGE'
        when 'OTHER_ON_AMAZON' then 'PLACEMENT_REST_OF_SEARCH'
        when 'OTHER ON-AMAZON' then 'PLACEMENT_REST_OF_SEARCH'
    end as placement_api_enum,
    coalesce((record->>'impressions')::bigint, 0) as impressions,
    coalesce((record->>'clicks')::bigint, 0) as clicks,
    coalesce((record->>'cost')::numeric(18,4), 0) as cost,
    coalesce((coalesce(record->>'purchases7d', record->>'purchases_7d'))::bigint, 0) as attributed_orders_7d,
    coalesce((coalesce(record->>'sales7d', record->>'sales_7d'))::numeric(18,4), 0) as attributed_sales_7d,
    coalesce((coalesce(record->>'unitsSoldClicks7d', record->>'units_sold_clicks_7d'))::bigint, 0) as attributed_units_7d,
    loaded_at
from ranked
where _rn = 1
