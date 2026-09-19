drop view if exists notification_consent_effective_state;
drop trigger if exists notification_consent_event_immutable on notification_consent_event;
drop function if exists protect_notification_consent_event();
drop function if exists notification_consent_effective(uuid, text, text, text);
drop table if exists notification_consent_event;
