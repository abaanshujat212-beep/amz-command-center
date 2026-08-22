-- Down: 0005_pipeline_run_detail.sql
--
-- Additive column, so this is a true inverse. Dropping it loses the per-run
-- detail payload the engine writes; the run rows themselves survive.

alter table pipeline_run drop column if exists detail;
