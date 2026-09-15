drop trigger if exists report_job_transition_guard on report_job;
drop function if exists enforce_report_job_transition();
drop trigger if exists report_definition_immutable on report_definition;
drop function if exists protect_report_definition_version();
drop table if exists report_job_event;
drop table if exists report_job;
drop table if exists report_definition;
