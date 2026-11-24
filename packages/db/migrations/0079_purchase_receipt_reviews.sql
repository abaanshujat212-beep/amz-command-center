-- Durable receiving evidence only: no inventory or accounting posting.
alter table supplier_purchase_order add constraint supplier_purchase_order_id_tenant unique(id,tenant_id);
create table purchase_receipt_review (
  id uuid primary key,
  tenant_id uuid not null references tenant(id) on delete cascade,
  order_id uuid not null,
  location_id uuid not null,
  source_ref text not null check (length(source_ref) between 1 and 200),
  observed_at timestamptz not null,
  actor_id uuid not null,
  evidence jsonb not null check (jsonb_typeof(evidence)='object'),
  created_at timestamptz not null default now(),
  unique(tenant_id,order_id,source_ref),
  foreign key(order_id,tenant_id) references supplier_purchase_order(id,tenant_id),
  foreign key(location_id,tenant_id) references inventory_location(id,tenant_id)
);
create index purchase_receipt_review_order on purchase_receipt_review(tenant_id,order_id,created_at);
alter table purchase_receipt_review enable row level security;
alter table purchase_receipt_review force row level security;
create policy purchase_receipt_review_tenant on purchase_receipt_review
  using(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
  with check(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
revoke update,delete,truncate on purchase_receipt_review from axaty_app;
grant select,insert on purchase_receipt_review to axaty_app;
