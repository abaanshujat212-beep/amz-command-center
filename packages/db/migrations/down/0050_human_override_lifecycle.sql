alter table action drop constraint if exists action_human_control_check;
alter table action drop constraint if exists action_control_tenant_fk;
alter table action drop column if exists request_origin;
alter table action drop column if exists control_id;
drop table if exists entity_automation_control_event;
drop table if exists entity_automation_control;
drop function if exists validate_entity_automation_control_event();
