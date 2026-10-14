drop index if exists idx_notification_attempt_delivery;
drop index if exists idx_notification_delivery_due;
drop trigger if exists notification_callback_immutable on notification_callback_event;
drop trigger if exists notification_attempt_immutable on notification_delivery_attempt;
drop function if exists protect_notification_delivery_evidence();
drop table if exists notification_callback_event;
drop table if exists notification_delivery_attempt;
alter table notification_delivery
  drop constraint if exists notification_delivery_dead_letter_check,
  drop constraint if exists fk_notification_delivery_template,
  drop column if exists dead_lettered_at,
  drop column if exists max_attempts,
  drop column if exists next_attempt_at,
  drop column if exists template_id,
  drop constraint if exists uq_notification_delivery_id_tenant;
drop table if exists notification_template;
