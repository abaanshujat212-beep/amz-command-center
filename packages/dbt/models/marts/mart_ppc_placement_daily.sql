-- Mart: placement-level KPIs. Read by the rules engine for scope = 'placement'.
--
-- Grain: one row per tenant, day, campaign and canonical placement.
--
-- Economics are NOT re-derived here. break_even_acos, margin and budget come
-- from mart_ppc_campaign_daily, because a campaign that is profitable in the
-- campaign view and unprofitable in the placement view would destroy trust in
-- both. One definition, one source.
--
-- account_cvr / account_ctr are computed from the placement rows themselves.
-- Placements partition every campaign, so their sum is the true account total.
-- These can differ very slightly from the same-named columns in
-- mart_ppc_keyword_daily, which are computed from the targeting report and so
-- exclude spend that never mapped to a keyword. That difference is expected --
-- do not "fix" it by pointing both at one report.

with pl as (

    select * from {{ ref('stg_ads_sp_placement_daily') }}

),

by_placement as (

    select
        tenant_id,
        report_date,
        campaign_id,
        campaign_name,
        campaign_status,
        placement,
        max(placement_api_enum)          as placement_api_enum,
        sum(impressions)                 as impressions,
        sum(clicks)                      as clicks,
        sum(cost)                        as cost,
        sum(attributed_orders_7d)        as attributed_orders_7d,
        sum(attributed_sales_7d)         as attributed_sales_7d,
        sum(attributed_units_7d)         as attributed_units_7d
    from pl
    group by 1, 2, 3, 4, 5, 6

),

campaign_economics as (

    select
        tenant_id,
        report_date,
        campaign_id,
        break_even_acos,
        contribution_margin_pct,
        economics_incomplete,
        budget_amount,
        budget_utilisation
    from {{ ref('mart_ppc_campaign_daily') }}

),

campaign_totals as (

    select
        tenant_id,
        report_date,
        campaign_id,
        sum(cost)   as campaign_cost,
        sum(clicks) as campaign_clicks
    from by_placement
    group by 1, 2, 3

),

account_benchmarks as (

    select
        tenant_id,
        report_date,
        case when sum(clicks) > 0
             then sum(attributed_orders_7d)::numeric / sum(clicks) end as account_cvr,
        case when sum(impressions) > 0
             then sum(clicks)::numeric / sum(impressions) end          as account_ctr
    from by_placement
    group by 1, 2

)

select
    p.tenant_id,
    p.report_date,
    p.campaign_id,
    p.campaign_name,
    p.campaign_status,
    p.placement,
    p.placement_api_enum,

    -- The rules engine keys cooldowns and claims on one entity id, and a
    -- placement modifier is set per campaign per placement -- so the entity is
    -- the pair, not the campaign.
    p.campaign_id || ':' || p.placement as placement_entity_id,

    -- Deliberately NULL until campaign placement-bidding config is ingested.
    -- A change action reads its current value from here; null makes an add_pct
    -- rule refuse rather than assume 0% and overwrite a real +50% modifier.
    null::numeric                       as placement_modifier_pct,

    p.impressions,
    p.clicks,
    p.cost,
    p.attributed_orders_7d,
    p.attributed_sales_7d,
    p.attributed_units_7d,

    -- KPIs, null-safe: no data must never look like zero performance
    case when p.attributed_sales_7d > 0 then p.cost / p.attributed_sales_7d end as acos,
    case when p.cost > 0 then p.attributed_sales_7d / p.cost end                as roas,
    case when p.impressions > 0 then p.clicks::numeric / p.impressions end      as ctr,
    case when p.clicks > 0 then p.attributed_orders_7d::numeric / p.clicks end  as cvr,
    case when p.clicks > 0 then p.cost / p.clicks end                           as cpc,

    -- How much of the campaign this placement actually is. A terrible placement
    -- holding 2% of spend is a note; holding 60% is the whole problem.
    case when t.campaign_cost > 0 then p.cost / t.campaign_cost end as spend_share,

    a.account_cvr,
    a.account_ctr,
    case
        when a.account_cvr is null or a.account_cvr = 0 then null
        when p.clicks = 0 then null
        else (p.attributed_orders_7d::numeric / p.clicks) / a.account_cvr
    end as cvr_index,

    c.break_even_acos,
    c.contribution_margin_pct,
    c.economics_incomplete,
    c.budget_amount,
    c.budget_utilisation,

    (p.report_date <= current_date - interval '{{ var("settlement_lag_days") }} days')
        as is_settled

from by_placement p
left join campaign_economics c
    on  p.tenant_id   = c.tenant_id
    and p.report_date = c.report_date
    and p.campaign_id = c.campaign_id
left join campaign_totals t
    on  p.tenant_id   = t.tenant_id
    and p.report_date = t.report_date
    and p.campaign_id = t.campaign_id
left join account_benchmarks a
    on  p.tenant_id   = a.tenant_id
    and p.report_date = a.report_date
