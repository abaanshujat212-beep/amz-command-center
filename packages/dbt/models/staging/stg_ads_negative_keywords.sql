-- Staging: existing negative keywords (campaign and ad group level).
--
-- This is CONFIGURATION state, not a report. It is a full snapshot each sync,
-- so we keep only the newest snapshot and treat a missing row as "not negative".
--
-- The engine relies on this to avoid re-proposing a negative that already
-- exists. Get it wrong and the approval queue fills with duplicates until
-- nobody reads it.

with source as (

    select * from {{ source('raw', 'raw_ads_negative_keywords') }}

),

latest_snapshot as (

    select tenant_id, max(loaded_at) as loaded_at
    from source
    group by 1

)

select
    s.tenant_id::uuid                  as tenant_id,
    s.campaign_id::text                as campaign_id,
    s.ad_group_id::text                as ad_group_id,
    s.keyword_id::text                 as keyword_id,
    lower(trim(s.keyword_text))::text  as keyword_text,
    s.match_type::text                 as match_type,   -- negativeExact | negativePhrase
    s.state::text                      as state,
    s.loaded_at
from source s
join latest_snapshot l
    on  s.tenant_id = l.tenant_id
    and s.loaded_at = l.loaded_at
where s.state = 'enabled'
