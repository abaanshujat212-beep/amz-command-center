-- Human ownership of an entity is distinct from allow/deny protection policy.
create table entity_automation_control (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  entity_type text not null check (entity_type in ('keyword','target','search_term','asin','campaign')),
  entity_id text not null check (btrim(entity_id) <> ''), product_scope text not null default '*',
  duration text not null check (duration in ('one_time','temporary','persistent')), expires_at timestamptz,
  reason text not null check (btrim(reason) <> ''), created_by uuid not null references auth.auth_user(id),
  created_at timestamptz not null default now(), unique(id,tenant_id),
  check ((duration='temporary' and expires_at is not null and expires_at>created_at) or (duration<>'temporary' and expires_at is null))
);
create table entity_automation_control_event (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  control_id uuid not null, state text not null check (state in ('HUMAN_OVERRIDE','LOCKED','REVIEW_DUE','AUTOMATED')),
  reason text not null check (btrim(reason) <> ''), actor_user_id uuid not null references auth.auth_user(id),
  occurred_at timestamptz not null default clock_timestamp(),
  foreign key(control_id,tenant_id) references entity_automation_control(id,tenant_id) on delete cascade
);
alter table action add column control_id uuid;
alter table action add column request_origin text not null default 'automation' check (request_origin in ('automation','human'));
alter table action add constraint action_control_tenant_fk foreign key(control_id,tenant_id) references entity_automation_control(id,tenant_id);
alter table action add constraint action_human_control_check check ((request_origin='human')=(control_id is not null));
create index entity_automation_control_lookup_idx on entity_automation_control(tenant_id,entity_type,lower(entity_id),product_scope,created_at desc);
create index entity_automation_control_event_latest_idx on entity_automation_control_event(tenant_id,control_id,occurred_at desc,id desc);
create function validate_entity_automation_control_event() returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
declare latest text; begin
  perform pg_advisory_xact_lock(hashtextextended(new.tenant_id::text||':'||new.control_id::text,0));
  select state into latest from entity_automation_control_event where tenant_id=new.tenant_id and control_id=new.control_id order by occurred_at desc,id desc limit 1;
  if latest is null and new.state not in ('HUMAN_OVERRIDE','LOCKED') then raise exception 'control must start in HUMAN_OVERRIDE or LOCKED'; end if;
  if latest='AUTOMATED' then raise exception 'an ended control is immutable'; end if;
  if latest is not null and new.state=latest then raise exception 'duplicate control state'; end if;
  return new;
end $$;
create trigger entity_automation_control_event_valid before insert on entity_automation_control_event for each row execute function validate_entity_automation_control_event();
create trigger entity_automation_control_immutable before update on entity_automation_control for each row execute function protect_configuration_version();
create trigger entity_automation_control_event_immutable before update on entity_automation_control_event for each row execute function protect_configuration_version();
do $$ declare t text; begin foreach t in array array['entity_automation_control','entity_automation_control_event'] loop
  execute format('alter table %I enable row level security',t); execute format('alter table %I force row level security',t);
  execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
end loop; end $$;
grant select,insert on entity_automation_control,entity_automation_control_event to axaty_app;
