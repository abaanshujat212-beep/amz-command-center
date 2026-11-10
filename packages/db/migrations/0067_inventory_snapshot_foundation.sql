-- Tenant-scoped inventory locations and append-only source observations.
create table inventory_location (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  location_code text not null check (btrim(location_code) <> ''),
  location_type text not null check (location_type in (
    'amazon_fba','amazon_awd','own_warehouse','third_party_logistics','prep_center',
    'supplier','in_transit','other'
  )),
  display_name text not null check (btrim(display_name) <> ''),
  marketplace_id text,
  external_location_id text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (id,tenant_id),
  unique (tenant_id,location_code),
  check (location_type <> 'amazon_fba' or marketplace_id is not null)
);

create table inventory_position_snapshot (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenant(id) on delete cascade,
  location_id uuid not null,
  sku text not null check (btrim(sku) <> ''),
  source_type text not null check (source_type in (
    'amazon_api','manual','csv_import','supplier_connector','warehouse_connector','approved_provider'
  )),
  source_provider_id text,
  source_reference text not null check (btrim(source_reference) <> ''),
  observed_at timestamptz not null,
  freshness_state text not null default 'current' check (freshness_state in ('current','stale','partial','unknown')),
  on_hand_qty numeric(16,4) check (on_hand_qty >= 0),
  available_qty numeric(16,4) check (available_qty >= 0),
  reserved_qty numeric(16,4) check (reserved_qty >= 0),
  inbound_qty numeric(16,4) check (inbound_qty >= 0),
  unsellable_qty numeric(16,4) check (unsellable_qty >= 0),
  committed_qty numeric(16,4) check (committed_qty >= 0),
  in_transit_qty numeric(16,4) check (in_transit_qty >= 0),
  expected_available_at timestamptz,
  currency char(3),
  source_payload jsonb not null default '{}'::jsonb check (jsonb_typeof(source_payload)='object'),
  created_at timestamptz not null default now(),
  foreign key (location_id,tenant_id) references inventory_location(id,tenant_id) on delete cascade,
  unique (tenant_id,source_type,source_reference,location_id,sku,observed_at),
  check (source_type <> 'approved_provider' or source_provider_id is not null),
  check (currency is null or currency ~ '^[A-Z]{3}$')
);

create index inventory_snapshot_lookup_idx
  on inventory_position_snapshot(tenant_id,sku,observed_at desc);
create index inventory_snapshot_location_idx
  on inventory_position_snapshot(tenant_id,location_id,observed_at desc);

do $$ declare t text; begin
  foreach t in array array['inventory_location','inventory_position_snapshot'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy tenant_isolation on %I using (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) with check (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',
      t
    );
  end loop;
end $$;

grant select,insert,update on inventory_location to axaty_app;
grant select,insert on inventory_position_snapshot to axaty_app;
