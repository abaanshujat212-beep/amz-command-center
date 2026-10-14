-- Tenant-safe supplier profiles, versioned quotes, private document metadata and timeline.
create or replace function supplier_documents_allowed() returns boolean
language sql stable as $$
  select coalesce(current_setting('app.access_scopes', true), '') ~ '(^|,)supplier:documents(,|$)'
$$;

create table supplier_profile (
  tenant_id uuid not null references tenant(id) on delete cascade,
  party_id uuid not null,
  status text not null default 'prospect' check (status in ('prospect','approved','paused','blocked')),
  default_currency char(3) not null default 'GBP' check (default_currency ~ '^[A-Z]{3}$'),
  default_lead_days integer check (default_lead_days is null or default_lead_days >= 0),
  payment_terms text,
  capabilities text[] not null default '{}', certifications text[] not null default '{}',
  quality_notes text, risk_notes text,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  primary key (tenant_id,party_id),
  foreign key (party_id,tenant_id) references party(id,tenant_id) on delete cascade
);

create table supplier_product (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  supplier_party_id uuid not null, sku text not null, product_name text not null,
  moq numeric(18,4) check (moq is null or moq > 0), lead_days integer check (lead_days is null or lead_days >= 0),
  notes text, active boolean not null default true, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique (id,tenant_id), unique (tenant_id,supplier_party_id,id), unique (tenant_id,supplier_party_id,sku),
  foreign key (tenant_id,supplier_party_id) references supplier_profile(tenant_id,party_id) on delete cascade
);

create table supplier_quote (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  supplier_party_id uuid not null, supplier_product_id uuid not null, quote_ref text not null,
  version integer not null check (version > 0), quoted_on date not null, valid_until date,
  currency char(3) not null check (currency ~ '^[A-Z]{3}$'), unit_price numeric(18,6) not null check (unit_price >= 0),
  moq numeric(18,4) check (moq is null or moq > 0), lead_days integer check (lead_days is null or lead_days >= 0),
  payment_terms text, notes text, superseded_at timestamptz, created_by uuid, created_at timestamptz not null default now(),
  unique (id,tenant_id), unique (tenant_id,supplier_party_id,quote_ref,version),
  foreign key (tenant_id,supplier_party_id) references supplier_profile(tenant_id,party_id) on delete cascade,
  foreign key (tenant_id,supplier_party_id,supplier_product_id) references supplier_product(tenant_id,supplier_party_id,id) on delete restrict,
  check (valid_until is null or valid_until >= quoted_on)
);
create unique index supplier_quote_one_current on supplier_quote(tenant_id,supplier_party_id,quote_ref) where superseded_at is null;

create table supplier_document (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  supplier_party_id uuid not null, document_type text not null check (document_type in ('quote','contract','certificate','quality','other')),
  title text not null, storage_key text not null, content_type text, byte_size bigint check (byte_size is null or byte_size >= 0),
  valid_until date, uploaded_by uuid, created_at timestamptz not null default now(),
  unique (id,tenant_id), unique (tenant_id,storage_key),
  foreign key (tenant_id,supplier_party_id) references supplier_profile(tenant_id,party_id) on delete cascade
);

create table supplier_timeline_event (
  id uuid primary key default gen_random_uuid(), tenant_id uuid not null references tenant(id) on delete cascade,
  supplier_party_id uuid not null, event_type text not null, summary text not null, detail jsonb not null default '{}',
  actor_user_id uuid, occurred_at timestamptz not null default now(),
  foreign key (tenant_id,supplier_party_id) references supplier_profile(tenant_id,party_id) on delete cascade
);

create index supplier_quote_freshness on supplier_quote(tenant_id,supplier_party_id,valid_until) where superseded_at is null;
create index supplier_timeline_recent on supplier_timeline_event(tenant_id,supplier_party_id,occurred_at desc);

do $$ declare t text; begin
  foreach t in array array['supplier_profile','supplier_product','supplier_quote','supplier_document','supplier_timeline_event'] loop
    execute format('alter table %I enable row level security',t); execute format('alter table %I force row level security',t);
    execute format('create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
  end loop;
end $$;
drop policy tenant_isolation on supplier_document;
create policy tenant_isolation on supplier_document using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid and supplier_documents_allowed()) with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid and supplier_documents_allowed());
grant execute on function supplier_documents_allowed() to axaty_app;
grant select,insert,update,delete on supplier_profile,supplier_product,supplier_quote,supplier_document,supplier_timeline_event to axaty_app;
