-- Reusable tenant-safe party, contact, role and relationship foundation.
create or replace function party_sensitive_allowed() returns boolean
language sql stable as $$
  select coalesce(current_setting('app.access_scopes', true), '') ~ '(^|,)contacts:sensitive(,|$)'
$$;

create table party (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  party_kind text not null check (party_kind in ('person','organization')),
  display_name text not null,
  legal_name text,
  normalized_name text not null,
  status text not null default 'active' check (status in ('active','merged','archived')),
  merged_into_party_id uuid,
  extension jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, party_kind, normalized_name),
  foreign key (merged_into_party_id, tenant_id) references party(id, tenant_id) on delete restrict,
  check (merged_into_party_id is null or merged_into_party_id <> id)
);

create table party_role (
  tenant_id uuid not null references tenant(id) on delete cascade,
  party_id uuid not null,
  role_type text not null check (role_type in ('supplier','agent','freight_forwarder','warehouse','customer','other')),
  extension jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (tenant_id, party_id, role_type),
  foreign key (party_id, tenant_id) references party(id, tenant_id) on delete cascade
);

create table contact (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  party_id uuid not null,
  full_name text not null,
  job_title text,
  extension jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, tenant_id),
  foreign key (party_id, tenant_id) references party(id, tenant_id) on delete cascade
);

create table contact_channel (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  contact_id uuid not null,
  channel_type text not null check (channel_type in ('email','phone','whatsapp','wechat','other')),
  value text not null,
  normalized_value text not null,
  label text,
  is_primary boolean not null default false,
  sensitivity text not null default 'internal' check (sensitivity in ('public','internal','restricted')),
  created_at timestamptz not null default now(),
  unique (tenant_id, channel_type, normalized_value),
  foreign key (contact_id, tenant_id) references contact(id, tenant_id) on delete cascade
);

create unique index contact_channel_one_primary
  on contact_channel (tenant_id, contact_id, channel_type) where is_primary;

create table party_address (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  party_id uuid not null,
  address_type text not null default 'business' check (address_type in ('business','billing','shipping','warehouse','other')),
  line1 text not null, line2 text, city text, region text, postal_code text, country_code text not null,
  sensitivity text not null default 'internal' check (sensitivity in ('public','internal','restricted')),
  extension jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  foreign key (party_id, tenant_id) references party(id, tenant_id) on delete cascade
);

create table party_relationship (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  from_party_id uuid not null,
  to_party_id uuid not null,
  relationship_type text not null,
  extension jsonb not null default '{}'::jsonb,
  valid_from date, valid_to date,
  created_at timestamptz not null default now(),
  foreign key (from_party_id, tenant_id) references party(id, tenant_id) on delete cascade,
  foreign key (to_party_id, tenant_id) references party(id, tenant_id) on delete cascade,
  unique (tenant_id, from_party_id, to_party_id, relationship_type),
  check (from_party_id <> to_party_id),
  check (valid_to is null or valid_from is null or valid_to >= valid_from)
);

create table party_merge_history (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  source_party_id uuid not null,
  target_party_id uuid not null,
  actor_user_id uuid,
  merged_at timestamptz not null default now(),
  foreign key (source_party_id, tenant_id) references party(id, tenant_id) on delete restrict,
  foreign key (target_party_id, tenant_id) references party(id, tenant_id) on delete restrict,
  check (source_party_id <> target_party_id)
);

create index party_search_idx on party (tenant_id, normalized_name);
create index contact_party_idx on contact (tenant_id, party_id);
create index party_relationship_from_idx on party_relationship (tenant_id, from_party_id);
create index party_relationship_to_idx on party_relationship (tenant_id, to_party_id);

-- Database-enforced tenant boundary and restricted-row field policy.
do $$
declare t text;
begin
  foreach t in array array['party','party_role','contact','contact_channel','party_address','party_relationship','party_merge_history'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy tenant_isolation on %I using (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid) with check (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid)', t);
  end loop;
end $$;

drop policy tenant_isolation on contact_channel;
create policy tenant_isolation on contact_channel
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid and (sensitivity <> 'restricted' or party_sensitive_allowed()))
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid and (sensitivity <> 'restricted' or party_sensitive_allowed()));
drop policy tenant_isolation on party_address;
create policy tenant_isolation on party_address
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid and (sensitivity <> 'restricted' or party_sensitive_allowed()))
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid and (sensitivity <> 'restricted' or party_sensitive_allowed()));

grant execute on function party_sensitive_allowed() to axaty_app;
grant select, insert, update, delete on party, party_role, contact, contact_channel, party_address, party_relationship, party_merge_history to axaty_app;
