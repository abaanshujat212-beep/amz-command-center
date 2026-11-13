-- Read-only campaign budget health signals over settled daily data.
-- Thresholds are indicators, not automated recommendations or policy violations.

with daily as (

    select *
    from {{ ref('mart_ppc_campaign_daily') }}
    where is_settled

), rolling as (

    select
        current_day.tenant_id,
        current_day.report_date,
        current_day.campaign_id,
        count(history.report_date) as settled_days_7d,
        sum(history.cost) as spend_7d,
        sum(history.attributed_sales_7d) as sales_7d,
        case when sum(history.attributed_sales_7d) > 0
             then sum(history.cost) / sum(history.attributed_sales_7d) end as acos_7d,
        min(history.break_even_acos) as break_even_acos_7d,
        bool_or(coalesce(history.economics_incomplete, true)) as economics_incomplete_7d,
        count(*) filter (where history.budget_utilisation >= 0.98) as capped_days_7d,
        sum(history.cost) / nullif(sum(history.budget_amount), 0) as budget_utilisation_7d
    from daily current_day
    join daily history
      on history.tenant_id = current_day.tenant_id
     and history.campaign_id = current_day.campaign_id
     and history.report_date between current_day.report_date - 6 and current_day.report_date
    group by 1, 2, 3

)

select
    d.tenant_id,
    d.report_date,
    d.campaign_id,
    d.campaign_name,
    d.campaign_status,
    d.budget_amount,
    d.cost as spend,
    d.impressions,
    d.budget_utilisation,
    case
        when d.budget_amount is null or d.budget_amount <= 0 then 'unknown'
        when d.budget_utilisation > 1 then 'over_budget_delivery'
        when d.budget_utilisation >= 0.98 then 'capped'
        when d.budget_utilisation < 0.50 then 'underspend'
        else 'on_track'
    end as budget_status,
    r.settled_days_7d,
    r.spend_7d,
    r.sales_7d,
    r.acos_7d,
    r.break_even_acos_7d,
    r.capped_days_7d,
    r.budget_utilisation_7d,
    case
        when d.budget_amount is null or d.budget_amount <= 0 then 'unknown'
        when r.capped_days_7d >= 3 then 'high'
        when r.capped_days_7d > 0 then 'watch'
        when r.settled_days_7d < 5 then 'insufficient_data'
        else 'low'
    end as exhaustion_risk,
    case
        when r.economics_incomplete_7d or r.break_even_acos_7d is null then 'unknown_economics'
        when r.acos_7d is null then 'no_attributed_sales'
        when d.cost = 0 and d.impressions = 0 and r.acos_7d <= r.break_even_acos_7d then 'profitable_dark'
        when r.budget_utilisation_7d >= 0.90 and r.acos_7d > r.break_even_acos_7d then 'inefficient_consumer'
        when r.acos_7d <= r.break_even_acos_7d then 'profitable'
        when r.acos_7d > r.break_even_acos_7d then 'inefficient'
        else 'unknown_economics'
    end as efficiency_signal
from daily d
join rolling r
  on r.tenant_id = d.tenant_id
 and r.report_date = d.report_date
 and r.campaign_id = d.campaign_id
