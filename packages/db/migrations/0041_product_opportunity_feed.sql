-- 0041_product_opportunity_feed.sql
-- Evidence-grounded scheduled research feeds; no provider or scraping adapter.

alter table research_observation
  add constraint uq_research_observation_id_tenant unique (id, tenant_id);

alter table alert drop constraint alert_kind_check;
alter table alert add constraint alert_kind_check check (kind in (
  'auth_expiring','auth_expired','pipeline_failed','data_stale','blast_radius_halt',
  'budget_guard','action_failed','economics_incomplete','low_inventory',
  'projected_stockout','reorder_due','inbound_delayed','excess_stock','unusual_demand',
  'report_ready','product_opportunity_digest'
));
alter table notification_event drop constraint notification_event_event_type_check;
alter table notification_event add constraint notification_event_event_type_check check (event_type in (
  'auth_expiring','auth_expired','pipeline_failed','data_stale','blast_radius_halt',
  'budget_guard','action_failed','economics_incomplete','low_inventory',
  'projected_stockout','reorder_due','inbound_delayed','excess_stock','unusual_demand',
  'report_ready','product_opportunity_digest'
));
alter table notification_route_preference drop constraint notification_route_preference_event_type_check;
alter table notification_route_preference add constraint notification_route_preference_event_type_check check (event_type in (
  '*','auth_expiring','auth_expired','pipeline_failed','data_stale','blast_radius_halt',
  'budget_guard','action_failed','economics_incomplete','low_inventory',
  'projected_stockout','reorder_due','inbound_delayed','excess_stock','unusual_demand',
  'report_ready','product_opportunity_digest'
));

create table opportunity_feed_schedule (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  project_id uuid not null,
  cadence text not null check (cadence in ('weekly','monthly')),
  run_time time without time zone not null,
  weekday smallint check (weekday between 0 and 6),
  month_day smallint check (month_day between 1 and 28),
  timezone text not null check (btrim(timezone) <> ''),
  digest_enabled boolean not null default false,
  recipient_user_id uuid references auth.auth_user(id) on delete restrict,
  enabled boolean not null default true,
  next_run_at timestamptz not null,
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, project_id),
  foreign key (project_id, tenant_id) references research_project(id, tenant_id) on delete cascade,
  check ((cadence='weekly') = (weekday is not null)),
  check ((cadence='monthly') = (month_day is not null)),
  check (not digest_enabled or recipient_user_id is not null)
);

create table opportunity_feed_run (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  schedule_id uuid not null,
  scheduled_for timestamptz not null,
  status text not null check (status in ('succeeded','blocked_readiness','blocked_recipient','failed')),
  reason text,
  notification_event_id uuid,
  created_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, schedule_id, scheduled_for),
  foreign key (schedule_id, tenant_id) references opportunity_feed_schedule(id, tenant_id) on delete cascade,
  foreign key (notification_event_id, tenant_id) references notification_event(id, tenant_id) on delete restrict
);

create table opportunity_feed_item (
  tenant_id uuid not null references tenant(id) on delete cascade,
  run_id uuid not null,
  candidate_id uuid not null,
  score_observation_id uuid not null,
  rank integer not null check (rank > 0),
  score numeric not null,
  created_at timestamptz not null default now(),
  primary key (tenant_id, run_id, candidate_id),
  unique (tenant_id, run_id, rank),
  foreign key (run_id, tenant_id) references opportunity_feed_run(id, tenant_id) on delete cascade,
  foreign key (candidate_id, tenant_id) references research_candidate(id, tenant_id) on delete restrict,
  foreign key (score_observation_id, tenant_id) references research_observation(id, tenant_id) on delete restrict
);

create index opportunity_feed_due_idx on opportunity_feed_schedule(tenant_id,next_run_at) where enabled;
create trigger opportunity_feed_timezone_valid
before insert or update of timezone on opportunity_feed_schedule
for each row execute function validate_report_schedule_timezone();
do $$ declare t text; begin
  foreach t in array array['opportunity_feed_schedule','opportunity_feed_run','opportunity_feed_item'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy tenant_isolation on %I using (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  end loop;
end $$;
grant select,insert,update,delete on opportunity_feed_schedule to axaty_app;
grant select,insert,update on opportunity_feed_run to axaty_app;
grant select,insert on opportunity_feed_item to axaty_app;
