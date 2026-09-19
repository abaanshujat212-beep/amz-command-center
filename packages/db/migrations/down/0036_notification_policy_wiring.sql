drop index if exists idx_notification_delivery_tenant_policy;
alter table notification_delivery
  drop column if exists policy_decision,
  drop column if exists eligible_at;
