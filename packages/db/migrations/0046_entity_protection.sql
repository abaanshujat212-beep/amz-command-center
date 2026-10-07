-- 0046_entity_protection.sql
-- Append-only allow/deny/protection controls for keywords, search terms and ASINs.

create table entity_protection (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  entity_type text not null check (entity_type in ('keyword','search_term','asin')),
  entity_value text not null check (btrim(entity_value) <> ''),
  product_scope text not null default '*' check (btrim(product_scope) <> ''),
  policy text not null check (policy in ('allow','deny','protect')),
  duration text not null check (duration in ('one_time','temporary','persistent')),
  expires_at timestamptz,
  reason text not null check (btrim(reason) <> ''),
  created_by uuid not null references auth.auth_user(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique(id,tenant_id),
  check ((duration='temporary' and expires_at is not null and expires_at > created_at)
      or (duration<>'temporary' and expires_at is null))
);

create table entity_protection_event (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  protection_id uuid not null,
  event_type text not null check (event_type in ('created','consumed','released')),
  reason text not null check (btrim(reason) <> ''),
  actor_user_id uuid not null references auth.auth_user(id) on delete restrict,
  occurred_at timestamptz not null default clock_timestamp(),
  foreign key(protection_id,tenant_id)
    references entity_protection(id,tenant_id) on delete cascade
);

create index entity_protection_lookup_idx
  on entity_protection(tenant_id,entity_type,lower(entity_value),product_scope,created_at desc);
create index entity_protection_event_latest_idx
  on entity_protection_event(tenant_id,protection_id,occurred_at desc,id desc);

create function validate_entity_protection_event() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$
declare latest text;
begin
  perform pg_advisory_xact_lock(
    hashtextextended(new.tenant_id::text || ':' || new.protection_id::text,0)
  );
  select event_type into latest from entity_protection_event
   where tenant_id=new.tenant_id and protection_id=new.protection_id
   order by occurred_at desc,id desc limit 1;
  if new.event_type='created' and latest is not null then
    raise exception 'protection already has a creation event';
  end if;
  if new.event_type in ('consumed','released') and latest is distinct from 'created' then
    raise exception 'only an active protection can transition';
  end if;
  return new;
end $$;
create trigger entity_protection_event_valid before insert on entity_protection_event
for each row execute function validate_entity_protection_event();

create function audit_entity_protection_created() returns trigger language plpgsql security invoker
set search_path=public,pg_temp as $$ begin
  insert into entity_protection_event(
    tenant_id,protection_id,event_type,reason,actor_user_id,occurred_at)
  values(new.tenant_id,new.id,'created',new.reason,new.created_by,clock_timestamp());
  return new;
end $$;
create trigger entity_protection_created after insert on entity_protection
for each row execute function audit_entity_protection_created();
create trigger entity_protection_immutable before update on entity_protection
for each row execute function protect_configuration_version();
create trigger entity_protection_event_immutable before update on entity_protection_event
for each row execute function protect_configuration_version();

do $$ declare t text; begin
  foreach t in array array['entity_protection','entity_protection_event'] loop
    execute format('alter table %I enable row level security',t);
    execute format('alter table %I force row level security',t);
    execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  end loop;
end $$;

grant select,insert on entity_protection,entity_protection_event to axaty_app;
