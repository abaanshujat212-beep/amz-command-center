-- Better Auth owns identity/session storage. tenant_member remains the only
-- source of tenant authorization and is still protected by FORCE RLS.
create schema if not exists auth;
revoke all on schema auth from public;
grant usage on schema auth to axaty_app;

create table if not exists auth.auth_user (
  id uuid primary key default gen_random_uuid(), name text not null,
  email text not null unique, email_verified boolean not null default false,
  image text, created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists auth.auth_session (
  id uuid primary key default gen_random_uuid(), expires_at timestamptz not null,
  token text not null unique, created_at timestamptz not null default now(),
  updated_at timestamptz not null, ip_address text, user_agent text,
  user_id uuid not null references auth.auth_user(id) on delete cascade,
  active_tenant_id uuid references public.tenant(id) on delete cascade
);
create table if not exists auth.auth_account (
  id uuid primary key default gen_random_uuid(), issuer text not null,
  account_id text not null, provider_id text not null,
  user_id uuid not null references auth.auth_user(id) on delete cascade,
  access_token text, refresh_token text, id_token text,
  access_token_expires_at timestamptz, refresh_token_expires_at timestamptz,
  scope text, password text, created_at timestamptz not null default now(),
  updated_at timestamptz not null
);
create table if not exists auth.auth_verification (
  id uuid primary key default gen_random_uuid(), identifier text not null,
  value text not null, expires_at timestamptz not null,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index if not exists auth_session_user_id_idx on auth.auth_session(user_id);
create index if not exists auth_account_user_id_idx on auth.auth_account(user_id);
create index if not exists auth_verification_identifier_idx on auth.auth_verification(identifier);
create unique index if not exists auth_account_issuer_account_id_uidx on auth.auth_account(issuer, account_id);
grant select, insert, update, delete on all tables in schema auth to axaty_app;

alter table tenant_member drop constraint if exists tenant_member_role_check;
alter table tenant_member add constraint tenant_member_role_check
  check (role in ('owner','admin','user','analyst','viewer'));
create unique index if not exists tenant_member_one_owner on tenant_member(tenant_id) where role = 'owner';
