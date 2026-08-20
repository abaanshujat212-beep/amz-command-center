-- 0001_tenancy.sql
-- Multi-tenant core. Every tenant-scoped table carries tenant_id and every
-- composite index leads with tenant_id.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------- tenants
create table if not exists tenant (
  id             uuid primary key default gen_random_uuid(),
  name           text        not null,
  plan           text        not null default 'internal',
  status         text        not null default 'active'
                 check (status in ('active','suspended','archived')),
  data_region    text        not null default 'eu',
  retention_days integer     not null default 1095,
  created_at     timestamptz not null default now()
);

create table if not exists tenant_member (
  tenant_id  uuid not null references tenant(id) on delete cascade,
  user_id    uuid not null,
  role       text not null check (role in ('owner','admin','analyst','viewer')),
  created_at timestamptz not null default now(),
  primary key (tenant_id, user_id)
);

create table if not exists tenant_settings (
  tenant_id           uuid primary key references tenant(id) on delete cascade,
  target_acos_default numeric(6,4) not null default 0.35,
  automation_enabled  boolean      not null default false,  -- kill switch, off by default
  dry_run             boolean      not null default true,   -- dry-run until explicitly promoted
  min_bid             numeric(10,2) not null default 0.02,
  max_bid             numeric(10,2) not null default 5.00,
  max_daily_budget    numeric(12,2) not null default 100.00,
  max_changes_per_day integer       not null default 50,
  timezone            text          not null default 'Europe/London',
  currency            text          not null default 'GBP'
);

create table if not exists tenant_quota (
  tenant_id     uuid primary key references tenant(id) on delete cascade,
  keepa_tokens_month integer not null default 0,
  api_calls_day      integer not null default 0,
  updated_at    timestamptz not null default now()
);

-- ------------------------------------------------------------ connections
-- authorization_expires_at is mandatory: SP-API seller authorization must be
-- re-confirmed every 12 months or Amazon suspends access silently.
create table if not exists amazon_connection (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null references tenant(id) on delete cascade,
  provider                 text not null check (provider in ('sp_api','ads_api')),
  region                   text not null default 'eu',
  status                   text not null default 'pending'
                           check (status in ('pending','active','expiring','expired','error','revoked')),
  lwa_client_ref           text,
  refresh_token_encrypted  bytea,
  key_version              integer not null default 1,
  scopes                   text[]  not null default '{}',
  authorized_at            timestamptz,
  authorization_expires_at timestamptz,
  last_refresh_at          timestamptz,
  last_error               text,
  created_at               timestamptz not null default now(),
  unique (tenant_id, provider, region)
);

create index if not exists idx_amazon_connection_expiry
  on amazon_connection (authorization_expires_at)
  where status in ('active','expiring');

create table if not exists ads_profile (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenant(id) on delete cascade,
  connection_id uuid not null references amazon_connection(id) on delete cascade,
  profile_id    bigint not null,
  country_code  text   not null,
  currency      text   not null,
  account_type  text,
  entity_id     text,
  created_at    timestamptz not null default now(),
  unique (tenant_id, profile_id)
);

create table if not exists selling_account (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenant(id) on delete cascade,
  connection_id        uuid not null references amazon_connection(id) on delete cascade,
  selling_partner_id   text not null,
  marketplace_ids      text[] not null default '{A1F83G8C2ARO7P}',
  created_at           timestamptz not null default now(),
  unique (tenant_id, selling_partner_id)
);

-- --------------------------------------------------------------- pipeline
create table if not exists sync_watermark (
  tenant_id          uuid not null references tenant(id) on delete cascade,
  dataset            text not null,
  last_complete_date date,
  last_attempt_at    timestamptz,
  last_status        text,
  primary key (tenant_id, dataset)
);

create table if not exists pipeline_run (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenant(id) on delete cascade,
  dataset     text not null,
  date_from   date,
  date_to     date,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text not null default 'running'
              check (status in ('running','success','partial','failed')),
  rows_loaded bigint default 0,
  error       text
);

create index if not exists idx_pipeline_run_tenant_started
  on pipeline_run (tenant_id, started_at desc);

-- ------------------------------------------------------------------ audit
create table if not exists audit_log (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenant(id) on delete cascade,
  actor_user_id  uuid,
  action         text not null,
  entity         text,
  before         jsonb,
  after          jsonb,
  at             timestamptz not null default now()
);

create index if not exists idx_audit_log_tenant_at on audit_log (tenant_id, at desc);
