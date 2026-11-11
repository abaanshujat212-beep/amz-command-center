import type { PoolClient } from "pg"
import { query } from "@/lib/db"

export type InventorySnapshotView = {
	snapshotId: string
	locationId: string
	locationCode: string
	locationName: string
	locationType: string
	marketplaceId: string | null
	sku: string
	sourceType: string
	sourceProviderId: string | null
	sourceReference: string
	observedAt: string
	freshness: "current" | "stale" | "partial" | "unknown"
	availableQty: number | null
	onHandQty: number | null
	reservedQty: number | null
	inboundQty: number | null
	unsellableQty: number | null
	committedQty: number | null
	inTransitQty: number | null
	expectedAvailableAt: string | null
}

export async function inventorySnapshotRead(
	client: PoolClient,
	tenantId: string,
	options: { sku?: string; locationCode?: string; page: number; pageSize: number; freshHours: number },
) {
	const offset = (options.page - 1) * options.pageSize
	const filters = [tenantId, options.sku ?? null, options.locationCode ?? null, options.freshHours]
	const rows = await query<InventorySnapshotView>(client, `
		with latest as (
			select distinct on (s.location_id,s.sku)
				s.id::text snapshot_id,l.id::text location_id,l.location_code,l.display_name location_name,
				l.location_type,l.marketplace_id,s.sku,s.source_type,s.source_provider_id,
				s.source_reference,s.observed_at::text observed_at,
				case when s.freshness_state <> 'current' then s.freshness_state
					 when s.observed_at > now() then 'unknown'
					 when s.observed_at < now() - ($4::int * interval '1 hour') then 'stale'
					 else 'current' end freshness,
				s.available_qty,s.on_hand_qty,s.reserved_qty,s.inbound_qty,s.unsellable_qty,
				s.committed_qty,s.in_transit_qty,s.expected_available_at::text expected_available_at
			from inventory_position_snapshot s
			join inventory_location l on l.id=s.location_id and l.tenant_id=s.tenant_id and l.active
			where s.tenant_id=$1 and ($2::text is null or s.sku=$2)
				and ($3::text is null or l.location_code=$3)
			order by s.location_id,s.sku,s.observed_at desc,s.id desc
		)
		select snapshot_id "snapshotId",location_id "locationId",location_code "locationCode",
			location_name "locationName",location_type "locationType",marketplace_id "marketplaceId",
			sku,source_type "sourceType",source_provider_id "sourceProviderId",source_reference "sourceReference",
			observed_at "observedAt",freshness,available_qty "availableQty",on_hand_qty "onHandQty",
			reserved_qty "reservedQty",inbound_qty "inboundQty",unsellable_qty "unsellableQty",
			committed_qty "committedQty",in_transit_qty "inTransitQty",expected_available_at "expectedAvailableAt"
		from latest
		order by sku,location_code limit $5 offset $6`,
	[...filters, options.pageSize, offset])
	const countRows = await query<{
		total: number; current: number; stale: number; partial: number; unknown: number
	}>(client, `
		select count(*)::int total,
			count(*) filter (where s.freshness_state = 'current' and s.observed_at <= now()
				and s.observed_at >= now()-($4::int*interval '1 hour'))::int current,
			count(*) filter (where s.freshness_state = 'stale' or (s.freshness_state = 'current'
				and s.observed_at < now()-($4::int*interval '1 hour')))::int stale,
			count(*) filter (where s.freshness_state = 'partial')::int partial,
			count(*) filter (where s.freshness_state = 'unknown' or (s.freshness_state = 'current'
				and s.observed_at > now()))::int unknown
		from inventory_position_snapshot s
		join inventory_location l on l.id=s.location_id and l.tenant_id=s.tenant_id and l.active
		where s.tenant_id=$1 and ($2::text is null or s.sku=$2)
			and ($3::text is null or l.location_code=$3)
			and not exists (
				select 1 from inventory_position_snapshot newer
				where newer.tenant_id=s.tenant_id and newer.location_id=s.location_id
					and newer.sku=s.sku and (newer.observed_at,newer.id)>(s.observed_at,s.id)
			)`, filters)
	const { total, ...counts } = countRows[0] ?? { total: 0, current: 0, stale: 0, partial: 0, unknown: 0 }
	return {
		snapshots: rows,
		pagination: { page: options.page, pageSize: options.pageSize, total },
		freshness: { ...counts, thresholdHours: options.freshHours, ready: total > 0 && counts.current === total },
	}
}

export async function inventoryForecastRead(client: PoolClient, tenantId: string, freshHours: number) {
	const rows = await query<{
		sku: string; available_qty: number | null; observed_at: string; freshness_state: string;
		units_ordered: number; observed_days: number; loaded_at: string;
	}>(client, `
		with latest_position as (
			select distinct on (s.location_id,s.sku) s.sku,s.available_qty,s.observed_at,
				s.freshness_state
			from inventory_position_snapshot s
			join inventory_location l on l.id=s.location_id and l.tenant_id=s.tenant_id and l.active
			where s.tenant_id=$1
			order by s.location_id,s.sku,s.observed_at desc,s.id desc
		), position_by_sku as (
			select sku,
				case when bool_or(available_qty is null) then null else sum(available_qty) end available_qty,
				min(observed_at) observed_at,
				bool_or(freshness_state = 'unknown' or observed_at > now()) source_unknown,
				bool_or(freshness_state = 'stale'
					or observed_at < now()-($2::int*interval '1 hour')) source_stale,
				bool_or(freshness_state = 'partial') source_partial
			from latest_position group by sku
		), sales as (
			select coalesce(record->>'sku',record->>'sellerSku') sku,report_date,
				coalesce((coalesce(record->>'units_ordered',record->>'unitsOrdered'))::numeric,0) units_ordered,
				loaded_at
			from raw.raw_sales_traffic_asin_daily
			where tenant_id=$1 and report_date >= current_date-30 and report_date < current_date
				and coalesce(record->>'sku',record->>'sellerSku') is not null
		), demand_by_sku as (
			select sku,sum(units_ordered) units_30d,count(distinct report_date)::int observed_days,
				max(loaded_at) loaded_at from sales group by sku
		)
		select p.sku,p.available_qty,p.observed_at::text observed_at,
			case when p.source_unknown then 'unknown'
				when p.source_stale then 'stale'
				when p.source_partial then 'partial'
				else 'current' end freshness_state,
			coalesce(d.units_30d,0)::int units_ordered,coalesce(d.observed_days,0)::int observed_days,
			coalesce(d.loaded_at::text,'') loaded_at
		from position_by_sku p left join demand_by_sku d using(sku) order by p.sku`, [tenantId, freshHours])
	return rows.map(row => {
		const blockers: string[] = []
		if (row.available_qty === null) blockers.push("available_now_unknown")
		if (row.observed_days < 14) blockers.push("sparse_demand_history")
		if (row.freshness_state !== "current") blockers.push(`inventory_${row.freshness_state}`)
		const avgDailyDemand = row.observed_days >= 14 ? row.units_ordered / 30 : null
		const daysOfSupply = avgDailyDemand && row.available_qty !== null ? row.available_qty / avgDailyDemand : null
		return {
			sku: row.sku, status: blockers.length ? "blocked" : "ready", blockers,
			assumptions: { demandWindowDays: 30, observedSalesDays: row.observed_days,
				salesLoadedAt: row.loaded_at || null, inventoryObservedAt: row.observed_at,
				seasonality: "not_applied", leadTime: "not_configured" },
			availableNow: row.available_qty, averageDailyDemand: avgDailyDemand,
			daysOfSupply, projectedStockoutDay: daysOfSupply === null ? null :
				new Date(Date.now() + daysOfSupply * 86400000).toISOString().slice(0, 10),
			confidence: blockers.length ? 0 : Math.min(1, row.observed_days / 30),
		}
	})
}
