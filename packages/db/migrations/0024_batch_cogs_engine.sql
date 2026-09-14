-- Versioned, reproducible batch COGS. Extends (does not replace) sku_cost_ledger.
create table cogs_method_policy (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  marketplace_id text not null default 'A1F83G8C2ARO7P',
  sku text not null,
  method text not null check (method in ('fifo','weighted_average','by_period')),
  valid_from date not null,
  valid_to date,
  currency text not null default 'GBP' check (currency ~ '^[A-Z]{3}$'),
  version integer not null check (version > 0),
  supersedes_id uuid,
  created_by uuid,
  created_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, marketplace_id, sku, version),
  foreign key (supersedes_id, tenant_id) references cogs_method_policy(id, tenant_id) on delete restrict,
  check (valid_to is null or valid_to > valid_from)
);
create unique index cogs_method_policy_open_idx
  on cogs_method_policy(tenant_id, marketplace_id, sku) where valid_to is null;

create table inventory_receipt_batch (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  marketplace_id text not null default 'A1F83G8C2ARO7P',
  sku text not null,
  source_ref text not null,
  received_at timestamptz not null,
  quantity numeric(18,6) not null check (quantity > 0),
  unit_cost numeric(18,6) not null check (unit_cost >= 0),
  currency text not null default 'GBP' check (currency ~ '^[A-Z]{3}$'),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, marketplace_id, source_ref)
);

create table cogs_adjustment (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  batch_id uuid not null,
  adjustment_type text not null check (adjustment_type in ('quantity','unit_cost','fx','write_off','return')),
  quantity_delta numeric(18,6) not null default 0,
  cost_delta numeric(18,6) not null default 0,
  currency text not null check (currency ~ '^[A-Z]{3}$'),
  reason text not null,
  effective_at timestamptz not null,
  created_by uuid,
  created_at timestamptz not null default now(),
  foreign key (batch_id, tenant_id) references inventory_receipt_batch(id, tenant_id) on delete restrict
);

create table cogs_calculation_run (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  marketplace_id text not null,
  sku text not null,
  policy_id uuid not null,
  method text not null check (method in ('fifo','weighted_average','by_period')),
  period_start date not null,
  period_end date not null,
  version integer not null check (version > 0),
  supersedes_run_id uuid,
  input_hash text not null,
  status text not null check (status in ('complete','incomplete','failed')),
  incomplete_reason text,
  calculated_at timestamptz not null default now(),
  unique (id, tenant_id),
  unique (tenant_id, marketplace_id, sku, period_start, period_end, version),
  foreign key (policy_id, tenant_id) references cogs_method_policy(id, tenant_id) on delete restrict,
  foreign key (supersedes_run_id, tenant_id) references cogs_calculation_run(id, tenant_id) on delete restrict,
  check (period_end >= period_start),
  check ((status = 'complete' and incomplete_reason is null) or status <> 'complete')
);

create table cogs_allocation (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  run_id uuid not null,
  sale_ref text not null,
  sold_at timestamptz not null,
  batch_id uuid,
  quantity numeric(18,6) not null,
  unit_cost numeric(18,6),
  allocated_cost numeric(18,6),
  currency text not null check (currency ~ '^[A-Z]{3}$'),
  sequence integer not null check (sequence >= 0),
  created_at timestamptz not null default now(),
  foreign key (run_id, tenant_id) references cogs_calculation_run(id, tenant_id) on delete restrict,
  foreign key (batch_id, tenant_id) references inventory_receipt_batch(id, tenant_id) on delete restrict,
  unique (tenant_id, run_id, sale_ref, sequence),
  check ((batch_id is null and unit_cost is null and allocated_cost is null) or
         (batch_id is not null and unit_cost is not null and allocated_cost is not null))
);

create index receipt_batch_sku_time_idx on inventory_receipt_batch(tenant_id, marketplace_id, sku, received_at, id);
create index cogs_run_sku_period_idx on cogs_calculation_run(tenant_id, marketplace_id, sku, period_end desc, version desc);
create index cogs_allocation_sale_idx on cogs_allocation(tenant_id, sale_ref, sequence);

do $$
declare t text;
begin
  foreach t in array array['cogs_method_policy','inventory_receipt_batch','cogs_adjustment','cogs_calculation_run','cogs_allocation'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy tenant_isolation on %I using (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid) with check (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid)', t);
    execute format('revoke all on %I from axaty_app', t);
    execute format('grant select, insert on %I to axaty_app', t);
  end loop;
end $$;
