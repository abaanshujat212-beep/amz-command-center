-- 0056_governed_report_execution.sql
-- Observable execution progress and the first mart-backed export contract.

alter table report_job
  add column progress_current bigint not null default 0 check (progress_current >= 0),
  add column progress_total bigint check (progress_total is null or progress_total >= 0),
  add column heartbeat_at timestamptz,
  add constraint report_job_progress_bounds check (
    progress_total is null or progress_current <= progress_total
  );

-- Definitions are immutable. Version two deliberately exports mart columns
-- without recalculating any KPI in the report worker.
insert into report_definition(
  tenant_id,code,version,title,source_contract,render_contract_version,definition
)
select id,'account-summary',2,'Campaign performance','mart-ppc-campaign-daily-v1',1,
       '{"columns":["report_date","campaign_id","campaign_name","campaign_status","targeting_type","impressions","clicks","cost","attributed_orders_7d","attributed_sales_7d","acos","roas","ctr","cvr","cpc","tacos","break_even_acos","economics_incomplete","is_settled"],"allowed_filters":["campaign_status","targeting_type"]}'::jsonb
  from tenant
on conflict(tenant_id,code,version) do nothing;

create index idx_report_job_running_heartbeat
  on report_job (tenant_id, heartbeat_at)
  where status = 'running';
