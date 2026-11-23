-- Internal, single-line PO snapshot. No provider, COGS or inventory side effects.
create table supplier_purchase_order (
  id uuid primary key,
  tenant_id uuid not null references tenant(id) on delete cascade,
  quote_id uuid not null,
  supplier_name text not null,
  product_sku text not null,
  product_name text not null,
  quote_ref text not null,
  quote_version integer not null check (quote_version > 0),
  currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
  unit_price numeric(18,6) not null check (unit_price >= 0),
  quantity numeric(12,4) not null check (quantity > 0),
  total numeric(30,10) generated always as (unit_price * quantity) stored,
  state text not null default 'draft' check (state in ('draft','issued','cancelled')),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (quote_id, tenant_id) references supplier_quote(id,tenant_id)
    deferrable initially deferred
);
create index supplier_purchase_order_recent on supplier_purchase_order(tenant_id,created_at desc);
alter table supplier_purchase_order enable row level security;
alter table supplier_purchase_order force row level security;
create policy supplier_purchase_order_tenant on supplier_purchase_order
  using (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
  with check (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
revoke update, delete, truncate on supplier_purchase_order from axaty_app;
grant select, insert, update (state,updated_at) on supplier_purchase_order to axaty_app;
