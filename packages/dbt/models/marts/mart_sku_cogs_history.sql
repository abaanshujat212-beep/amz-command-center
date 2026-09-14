-- Reproducible allocation history; latest version is explicit, never an in-place rewrite.
with ranked_runs as (
  select *, row_number() over (
    partition by tenant_id, marketplace_id, sku, period_start, period_end
    order by version desc, calculated_at desc
  ) as version_rank
  from {{ source('app', 'cogs_calculation_run') }}
), allocations as (
  select tenant_id, run_id,
         sum(quantity) as allocated_quantity,
         sum(allocated_cost) as allocated_cogs,
         bool_or(allocated_cost is null) as has_unallocated_quantity
  from {{ source('app', 'cogs_allocation') }}
  group by 1, 2
)
select r.tenant_id, r.marketplace_id, r.sku, r.period_start, r.period_end,
       r.version, r.method, r.input_hash, r.status, r.incomplete_reason,
       a.allocated_quantity, a.allocated_cogs, a.has_unallocated_quantity,
       (r.version_rank = 1) as is_latest_version, r.calculated_at
from ranked_runs r
left join allocations a on a.tenant_id = r.tenant_id and a.run_id = r.id
