-- 0055_notification_delivery_governance.sql
-- Governed templates and append-only delivery/callback evidence for the existing router.

create table notification_template (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  event_type text not null check (event_type in (
    '*','auth_expiring','auth_expired','pipeline_failed','data_stale',
    'blast_radius_halt','budget_guard','action_failed','economics_incomplete',
    'low_inventory','projected_stockout','reorder_due','inbound_delayed',
    'excess_stock','unusual_demand','report_ready','product_opportunity_digest'
  )),
  channel text not null check (channel in ('email','whatsapp','sms')),
  locale text not null default 'en-GB' check (locale ~ '^[a-z]{2}(-[A-Z]{2})?$'),
  status text not null default 'DRAFT' check (status in ('DRAFT','APPROVED','DISABLED')),
  subject_template text,
  body_template text not null check (btrim(body_template) <> '' and length(body_template) <= 10000),
  variable_allowlist text[] not null default '{}',
  provider_template_ref text,
  created_by uuid,
  approved_by uuid,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, event_type, channel, locale),
  check ((status = 'APPROVED') = (approved_by is not null and approved_at is not null)),
  check (channel = 'email' or subject_template is null)
);

alter table notification_delivery
  add constraint uq_notification_delivery_id_tenant unique (id, tenant_id),
  add column template_id uuid,
  add column next_attempt_at timestamptz,
  add column max_attempts integer not null default 5 check (max_attempts between 1 and 10),
  add column dead_lettered_at timestamptz,
  add constraint fk_notification_delivery_template
    foreign key (template_id, tenant_id) references notification_template(id, tenant_id) on delete restrict,
  add constraint notification_delivery_dead_letter_check
    check ((status = 'DEAD_LETTER') = (dead_lettered_at is not null));

create table notification_delivery_attempt (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  delivery_id uuid not null,
  attempt_number integer not null check (attempt_number > 0),
  idempotency_key text not null check (btrim(idempotency_key) <> ''),
  outcome text not null check (outcome in ('DELIVERED','RETRYABLE','FAILED','DEAD_LETTER')),
  provider_reference text,
  provider_status text,
  error_code text,
  error_detail text,
  cost_amount numeric(14,6) not null default 0 check (cost_amount >= 0),
  cost_currency text,
  attempted_at timestamptz not null default now(),
  unique (tenant_id, delivery_id, attempt_number),
  unique (tenant_id, idempotency_key),
  foreign key (delivery_id, tenant_id) references notification_delivery(id, tenant_id) on delete cascade,
  check (cost_amount = 0 or btrim(cost_currency) <> '')
);

create table notification_callback_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  delivery_id uuid not null,
  channel text not null check (channel in ('email','whatsapp','sms')),
  provider_callback_id text not null check (btrim(provider_callback_id) <> ''),
  delivery_status text not null check (delivery_status in ('DELIVERED','FAILED','RETRYABLE')),
  signature_verified boolean not null check (signature_verified),
  provider_reference text,
  received_at timestamptz not null default now(),
  unique (tenant_id, channel, provider_callback_id),
  foreign key (delivery_id, tenant_id) references notification_delivery(id, tenant_id) on delete cascade
);

create function protect_notification_delivery_evidence() returns trigger
language plpgsql security invoker set search_path=public,pg_temp as $$
begin raise exception 'notification delivery evidence is immutable'; end $$;
create trigger notification_attempt_immutable before update or delete on notification_delivery_attempt
for each row execute function protect_notification_delivery_evidence();
create trigger notification_callback_immutable before update or delete on notification_callback_event
for each row execute function protect_notification_delivery_evidence();

create index idx_notification_delivery_due
  on notification_delivery(tenant_id, status, next_attempt_at) where status in ('PENDING','RETRYABLE');
create index idx_notification_attempt_delivery
  on notification_delivery_attempt(tenant_id, delivery_id, attempted_at desc);

alter table notification_template enable row level security;
alter table notification_template force row level security;
create policy tenant_isolation on notification_template
  using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
  with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
alter table notification_delivery_attempt enable row level security;
alter table notification_delivery_attempt force row level security;
create policy tenant_isolation on notification_delivery_attempt
  using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
  with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
alter table notification_callback_event enable row level security;
alter table notification_callback_event force row level security;
create policy tenant_isolation on notification_callback_event
  using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
  with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);

revoke all on notification_template, notification_delivery_attempt, notification_callback_event from axaty_app;
grant select,insert,update on notification_template to axaty_app;
grant select,insert on notification_delivery_attempt, notification_callback_event to axaty_app;
grant select,update on notification_delivery to axaty_app;
