-- Raw Keepa product snapshots keyed by ASIN.
create table if not exists raw.raw_keepa_product_snapshot (
  tenant_id uuid not null references tenant(id) on delete cascade,
  asin text not null,
  captured_at timestamptz not null default now(),
  title text,
  brand text,
  buy_box_price numeric(12,4),
  sales_rank integer,
  review_count integer,
  rating numeric(4,2),
  offer_count integer,
  record jsonb not null default '{}'::jsonb,
  primary key (tenant_id, asin, captured_at)
);

create index if not exists idx_raw_keepa_product_snapshot_latest
  on raw.raw_keepa_product_snapshot (tenant_id, asin, captured_at desc);
