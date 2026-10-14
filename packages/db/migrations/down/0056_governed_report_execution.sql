drop index if exists idx_report_job_running_heartbeat;
delete from report_definition where code='account-summary' and version=2
  and source_contract='mart-ppc-campaign-daily-v1';
alter table report_job
  drop constraint if exists report_job_progress_bounds,
  drop column if exists heartbeat_at,
  drop column if exists progress_total,
  drop column if exists progress_current;
