drop trigger if exists notification_provider_state_audit_immutable on notification_provider_state_audit;
drop trigger if exists notification_provider_state_audit on notification_provider_state;
drop function if exists protect_notification_provider_audit();
drop function if exists audit_notification_provider_state();
drop table if exists notification_provider_state_audit;
drop table if exists notification_provider_state;
