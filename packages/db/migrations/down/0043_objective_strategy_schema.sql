drop table if exists configuration_version_event;
drop table if exists configuration_run_binding;
drop table if exists strategy_version;
drop table if exists objective_version;
drop function if exists protect_configuration_version();
drop function if exists audit_configuration_version_created();
drop function if exists validate_configuration_guardrails(jsonb);
