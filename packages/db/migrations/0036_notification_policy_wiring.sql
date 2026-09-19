-- 0036_notification_policy_wiring.sql
-- Persist policy decisions made by the canonical router without claiming external delivery.

alter table notification_delivery
  add column policy_decision text not null default 'BLOCKED_CONFIGURATION'
    check (policy_decision in (
      'IMMEDIATE','BLOCKED_DISABLED','BLOCKED_CONSENT','BLOCKED_CONFIGURATION',
      'DEFERRED_QUIET_HOURS','QUEUED_DIGEST','ELIGIBLE'
    )),
  add column eligible_at timestamptz;

create index idx_notification_delivery_tenant_policy
  on notification_delivery (tenant_id, policy_decision, created_at desc);

grant select, update on notification_delivery to axaty_app;
