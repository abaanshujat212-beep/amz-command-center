-- Transparent current-month spend/sales scenarios from settled campaign data.
-- Successful pipeline runs define observed days, including valid zero-activity
-- days; absent or failed-run days are estimated from observed daily averages.

with account_limits as (

    select distinct on (tenant_id)
        tenant_id,
        limit_amount,
        currency,
        timezone as limit_timezone,
        effective_from,
        effective_to
    from {{ source('app', 'portfolio_budget_limit') }}
    where scope_type = 'account'
      and scope_id = '*'
      and period_type = 'monthly'
      and effective_from <= (current_timestamp at time zone timezone)::date
      and (effective_to is null or effective_to >= (current_timestamp at time zone timezone)::date)
    order by tenant_id, version desc

), settings as (

    select
        ts.tenant_id,
        ts.currency as tenant_currency,
        ts.timezone as tenant_timezone,
        ts.settlement_lag_days,
        l.limit_amount as monthly_limit,
        l.currency as limit_currency,
        coalesce(l.limit_timezone, ts.timezone) as reporting_timezone
    from {{ source('app', 'tenant_settings') }} ts
    left join account_limits l on l.tenant_id = ts.tenant_id

), periods as (

    select
        *,
        (current_timestamp at time zone reporting_timezone)::date as local_today,
        date_trunc('month', current_timestamp at time zone reporting_timezone)::date as month_start,
        (date_trunc('month', current_timestamp at time zone reporting_timezone) + interval '1 month - 1 day')::date as month_end
    from settings

), bounds as (

    select
        *,
        least(local_today - settlement_lag_days, month_end) as settled_through,
        greatest(0, least(local_today - settlement_lag_days, month_end) - month_start + 1) as elapsed_days
    from periods

), calendar as (

    select
        b.tenant_id,
        gs::date as report_date
    from bounds b
    cross join lateral generate_series(b.month_start, b.settled_through, interval '1 day') gs
    where b.elapsed_days > 0

), covered_days as (

    select distinct c.tenant_id, c.report_date
    from calendar c
    join {{ source('app', 'pipeline_run') }} r
      on r.tenant_id = c.tenant_id
     and r.dataset = 'ads_sp_campaign_daily'
     and r.status = 'success'
     and r.date_from <= c.report_date
     and r.date_to >= c.report_date

), daily as (

    select
        p.tenant_id,
        p.report_date,
        sum(p.cost) as spend,
        sum(p.attributed_sales_7d) as sales
    from {{ ref('mart_ppc_campaign_daily') }} p
    join bounds b on b.tenant_id = p.tenant_id
    -- Use this tenant's local settlement boundary, not a global DBT session
    -- date, so the forecast follows the account's configured timezone/lag.
    where p.report_date between b.month_start and b.settled_through
    group by 1, 2

), observations as (

    select
        c.tenant_id,
        c.report_date,
        coalesce(d.spend, 0)::numeric as spend,
        coalesce(d.sales, 0)::numeric as sales
    from covered_days c
    left join daily d using (tenant_id, report_date)

), aggregates as (

    select
        b.tenant_id,
        b.tenant_currency,
        b.reporting_timezone,
        b.month_start,
        b.month_end,
        b.settled_through,
        b.elapsed_days,
        greatest(0, b.month_end - b.settled_through) as remaining_days,
        b.monthly_limit,
        b.limit_currency,
        count(o.report_date)::integer as covered_days,
        coalesce(sum(o.spend), 0)::numeric as observed_spend,
        coalesce(sum(o.sales), 0)::numeric as observed_sales,
        avg(o.spend)::numeric as mean_daily_spend,
        avg(o.sales)::numeric as mean_daily_sales,
        coalesce(stddev_pop(o.spend), 0)::numeric as stddev_daily_spend,
        coalesce(stddev_pop(o.sales), 0)::numeric as stddev_daily_sales
    from bounds b
    left join observations o on o.tenant_id = b.tenant_id
    group by 1, 2, 3, 4, 5, 6, 7, 8, 9, 10

), volatility as (

    select
        *,
        covered_days::numeric / nullif(elapsed_days, 0) as coverage_ratio,
        case when mean_daily_spend > 0 then stddev_daily_spend / mean_daily_spend
             when stddev_daily_spend = 0 then 0 else 1 end as spend_cv,
        case when mean_daily_sales > 0 then stddev_daily_sales / mean_daily_sales
             when stddev_daily_sales = 0 then 0 else 1 end as sales_cv
    from aggregates

), scored as (

    select
        *,
        least(1::numeric, coalesce(coverage_ratio, 0))
        * least(1::numeric, covered_days::numeric / 14)
        * (1 - least(1::numeric, greatest(spend_cv, sales_cv)) * 0.5) as confidence_score,
        greatest(0, mean_daily_spend - stddev_daily_spend) as low_daily_spend,
        mean_daily_spend + stddev_daily_spend as high_daily_spend,
        greatest(0, mean_daily_sales - stddev_daily_sales) as low_daily_sales,
        mean_daily_sales + stddev_daily_sales as high_daily_sales
    from volatility

)

select
    tenant_id,
    tenant_currency,
    reporting_timezone,
    month_start,
    month_end,
    settled_through,
    elapsed_days,
    remaining_days,
    covered_days,
    greatest(0, elapsed_days - covered_days) as missing_days,
    case when elapsed_days > 0 then coverage_ratio end as coverage_ratio,
    observed_spend,
    observed_sales,
    case when covered_days > 0 then observed_spend + mean_daily_spend * (elapsed_days - covered_days) end as estimated_spend_to_date,
    case when covered_days > 0 then observed_sales + mean_daily_sales * (elapsed_days - covered_days) end as estimated_sales_to_date,
    case when covered_days > 0 then observed_spend + mean_daily_spend * (elapsed_days - covered_days + remaining_days) end as spend_forecast_base,
    case when covered_days > 0 then observed_spend + low_daily_spend * (elapsed_days - covered_days + remaining_days) end as spend_forecast_low,
    case when covered_days > 0 then observed_spend + high_daily_spend * (elapsed_days - covered_days + remaining_days) end as spend_forecast_high,
    case when covered_days > 0 then observed_sales + mean_daily_sales * (elapsed_days - covered_days + remaining_days) end as sales_forecast_base,
    case when covered_days > 0 then observed_sales + low_daily_sales * (elapsed_days - covered_days + remaining_days) end as sales_forecast_low,
    case when covered_days > 0 then observed_sales + high_daily_sales * (elapsed_days - covered_days + remaining_days) end as sales_forecast_high,
    monthly_limit,
    limit_currency,
    case
        when monthly_limit is null then 'NO_LIMIT_CONFIGURED'
        when limit_currency <> tenant_currency then 'CURRENCY_MISMATCH'
        when covered_days = 0 then 'NO_DATA'
        when observed_spend + mean_daily_spend * (elapsed_days - covered_days + remaining_days) > monthly_limit then 'PROJECTED_OVER_LIMIT'
        else 'WITHIN_LIMIT'
    end as limit_status,
    confidence_score,
    case
        when covered_days = 0 or elapsed_days = 0 then 'INSUFFICIENT_DATA'
        when covered_days < 7 or coverage_ratio < 0.70 then 'LOW'
        when coverage_ratio < 0.90 or confidence_score < 0.45 then 'MEDIUM'
        else 'HIGH'
    end as confidence,
    spend_cv,
    sales_cv,
    'Mean daily settled spend/sales from successful campaign-report dates; missing elapsed dates use the covered-day mean. Low/high scenarios use one population standard deviation and are not statistical guarantees.'::text as assumptions
from scored
