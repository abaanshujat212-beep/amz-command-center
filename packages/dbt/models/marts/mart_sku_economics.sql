-- Mart: per-SKU unit economics and break-even ACOS.
--
-- This is the most important model in the project. Every rule threshold is
-- expressed relative to break_even_acos. If this is wrong or missing, the whole
-- automation layer is making confident decisions with no idea what profit is.
--
-- break_even_acos = contribution_margin / price
--   i.e. the ACOS at which an extra advertised sale earns exactly zero.
--   Above it, we pay for the privilege of selling.

with latest_costs as (

    select
        tenant_id,
        sku,
        asin,
        cogs,
        freight_in,
        amazon_referral_pct,
        fba_fee,
        storage_est,
        vat_rate,
        currency,
        valid_from,
        row_number() over (
            partition by tenant_id, sku
            order by valid_from desc
        ) as _rn
    from {{ source('app', 'sku_cost_ledger') }}
    where valid_to is null
       or valid_to > current_date

),

prices as (

    -- average realised price over the last 30 settled days, which reflects
    -- promotions and coupons better than the list price does
    select
        tenant_id,
        child_asin as asin,
        sum(ordered_product_sales) / nullif(sum(units_ordered), 0) as avg_price,
        sum(units_ordered) as units_30d
    from {{ ref('stg_sales_traffic_asin_daily') }}
    where report_date >= current_date - interval '30 days'
    group by 1, 2

),

joined as (

    select
        c.tenant_id,
        c.sku,
        c.asin,
        c.currency,
        p.avg_price,
        p.units_30d,
        c.cogs,
        c.freight_in,
        c.fba_fee,
        c.storage_est,
        c.amazon_referral_pct,
        c.vat_rate,
        -- VAT is not ours to keep: strip it before measuring margin
        p.avg_price / (1 + c.vat_rate)                        as net_price,
        p.avg_price / (1 + c.vat_rate) * c.amazon_referral_pct as referral_fee
    from latest_costs c
    left join prices p
        on  c.tenant_id = p.tenant_id
        and c.asin      = p.asin
    where c._rn = 1

)

select
    tenant_id,
    sku,
    asin,
    currency,
    avg_price,
    net_price,
    units_30d,

    cogs,
    freight_in,
    fba_fee,
    storage_est,
    referral_fee,

    (cogs + freight_in + fba_fee + storage_est + referral_fee) as total_unit_cost,

    (net_price - cogs - freight_in - fba_fee - storage_est - referral_fee)
        as contribution_margin,

    case when net_price > 0 then
        (net_price - cogs - freight_in - fba_fee - storage_est - referral_fee)
        / net_price
    end as contribution_margin_pct,

    -- The number every rule compares against.
    case when net_price > 0 then
        greatest(
            (net_price - cogs - freight_in - fba_fee - storage_est - referral_fee)
            / net_price,
            0
        )
    end as break_even_acos,

    -- Fail loudly rather than quietly: a SKU with no price or no costs must not
    -- silently receive a plausible-looking break-even number.
    (avg_price is null or cogs is null) as economics_incomplete

from joined
