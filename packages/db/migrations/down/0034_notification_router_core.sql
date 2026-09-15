drop trigger if exists alert_notification_route on alert;
drop function if exists route_alert_to_notification();
drop trigger if exists notification_event_immutable on notification_event;
drop function if exists protect_notification_event();

drop table if exists notification_delivery;

alter table alert drop constraint if exists fk_alert_notification_event_tenant;
drop table if exists notification_event;

drop index if exists uq_alert_tenant_dedupe;
alter table alert
  drop constraint if exists alert_dedupe_key_nonempty,
  drop constraint if exists uq_alert_id_tenant,
  drop column if exists notification_event_id,
  drop column if exists dedupe_key;

alter table alert drop constraint if exists alert_kind_check;
alter table alert add constraint alert_kind_check check (kind in (
  'auth_expiring','auth_expired','pipeline_failed','data_stale',
  'blast_radius_halt','budget_guard','action_failed','economics_incomplete'
));
