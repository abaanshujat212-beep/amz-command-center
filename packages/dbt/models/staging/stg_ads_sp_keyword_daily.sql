with source as (
    select * from {{ source('raw', 'raw_ads_sp_keyword_daily') }}
), ranked as (
    select *, row_number() over (partition by tenant_id, report_date, entity_id order by loaded_at desc) as _rn
    from source
)
select
    tenant_id::uuid as tenant_id,
    report_date::date as report_date,
    coalesce(record->>'campaignId', record->>'campaign_id')::text as campaign_id,
    coalesce(record->>'campaignName', record->>'campaign_name')::text as campaign_name,
    coalesce(record->>'adGroupId', record->>'ad_group_id')::text as ad_group_id,
    coalesce(record->>'keywordId', record->>'targetingId', record->>'keyword_id', entity_id)::text as keyword_id,
    coalesce(record->>'keywordText', record->>'targetingText', record->>'keyword_text')::text as keyword_text,
    lower(coalesce(record->>'matchType', record->>'match_type'))::text as match_type,
    coalesce(record->>'keywordStatus', record->>'targetingStatus', record->>'keyword_status')::text as keyword_status,
    (coalesce(record->>'keywordBid', record->>'bid', record->>'keyword_bid'))::numeric(12,2) as bid,
    coalesce((record->>'impressions')::bigint, 0) as impressions,
    coalesce((record->>'clicks')::bigint, 0) as clicks,
    coalesce((record->>'cost')::numeric(18,4), 0) as cost,
    coalesce((coalesce(record->>'purchases7d', record->>'purchases_7d'))::bigint, 0) as attributed_orders_7d,
    coalesce((coalesce(record->>'sales7d', record->>'sales_7d'))::numeric(18,4), 0) as attributed_sales_7d,
    coalesce((coalesce(record->>'unitsSoldClicks7d', record->>'units_sold_clicks_7d'))::bigint, 0) as attributed_units_7d,
    case when coalesce(record->>'topOfSearchImpressionShare', record->>'top_of_search_impression_share') is null then null
         else (coalesce(record->>'topOfSearchImpressionShare', record->>'top_of_search_impression_share'))::numeric / 100.0
    end as top_of_search_impression_share,
    loaded_at
from ranked
where _rn = 1
