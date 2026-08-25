with source as (
    select * from {{ source('raw', 'raw_ads_placement_config') }}
), ranked as (
    select *, row_number() over (partition by tenant_id, campaign_id, placement order by loaded_at desc) as _rn
    from source
)
select
    tenant_id::uuid as tenant_id,
    campaign_id::text as campaign_id,
    placement::text as placement_api_enum,
    case placement
        when 'PLACEMENT_TOP' then 'top_of_search'
        when 'PLACEMENT_PRODUCT_PAGE' then 'product_page'
        when 'PLACEMENT_REST_OF_SEARCH' then 'rest_of_search'
        else 'unknown'
    end as placement,
    percentage::numeric as placement_modifier_pct,
    loaded_at
from ranked
where _rn = 1
