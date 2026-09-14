drop view if exists v_action_execution_history;
drop table if exists action_execution_event;
alter table action drop constraint if exists action_id_tenant_unique;
