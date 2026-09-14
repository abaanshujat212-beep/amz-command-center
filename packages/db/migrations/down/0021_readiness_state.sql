drop trigger if exists module_state_audit on module_state;
drop trigger if exists external_dependency_state_audit on external_dependency_state;
drop function if exists audit_readiness_transition();
drop table if exists module_state;
drop table if exists external_dependency_state;
