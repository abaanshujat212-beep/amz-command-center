-- 0029_business_context_hierarchy.sql
-- Explicit tenant-owned Amazon hierarchy. Existing provider rows are referenced,
-- never copied or automatically mapped from names.

create unique index if not exists selling_account_tenant_id_id_uidx
  on selling_account(tenant_id, id);
create unique index if not exists ads_profile_tenant_id_id_uidx
  on ads_profile(tenant_id, id);

create table brand (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  name text not null check (btrim(name) <> ''),
  slug text not null check (btrim(slug) <> ''),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, slug)
);

create table channel_account (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  brand_id uuid not null,
  channel text not null default 'amazon' check (channel = 'amazon'),
  label text not null check (btrim(label) <> ''),
  selling_account_id uuid,
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, brand_id, label),
  foreign key (tenant_id, brand_id)
    references brand(tenant_id, id) on delete cascade,
  foreign key (tenant_id, selling_account_id)
    references selling_account(tenant_id, id) on delete restrict
);

create unique index channel_account_selling_account_uidx
  on channel_account(tenant_id, selling_account_id)
  where selling_account_id is not null;

create table marketplace_context (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  channel_account_id uuid not null,
  marketplace_id text not null check (btrim(marketplace_id) <> ''),
  country_code text not null check (btrim(country_code) <> ''),
  currency text not null check (btrim(currency) <> ''),
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, channel_account_id, marketplace_id),
  foreign key (tenant_id, channel_account_id)
    references channel_account(tenant_id, id) on delete cascade
);

create table advertising_profile_context (
  tenant_id uuid not null references tenant(id) on delete cascade,
  marketplace_context_id uuid not null,
  ads_profile_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (tenant_id, marketplace_context_id, ads_profile_id),
  unique (tenant_id, ads_profile_id),
  foreign key (tenant_id, marketplace_context_id)
    references marketplace_context(tenant_id, id) on delete cascade,
  foreign key (tenant_id, ads_profile_id)
    references ads_profile(tenant_id, id) on delete restrict
);

create index brand_tenant_idx on brand(tenant_id, created_at);
create index channel_account_tenant_idx on channel_account(tenant_id, brand_id);
create index marketplace_context_tenant_idx
  on marketplace_context(tenant_id, channel_account_id);

alter table brand enable row level security;
alter table brand force row level security;
create policy tenant_isolation on brand
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

alter table channel_account enable row level security;
alter table channel_account force row level security;
create policy tenant_isolation on channel_account
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

alter table marketplace_context enable row level security;
alter table marketplace_context force row level security;
create policy tenant_isolation on marketplace_context
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

alter table advertising_profile_context enable row level security;
alter table advertising_profile_context force row level security;
create policy tenant_isolation on advertising_profile_context
  using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

grant select, insert, update, delete
  on brand, channel_account, marketplace_context, advertising_profile_context
  to axaty_app;
