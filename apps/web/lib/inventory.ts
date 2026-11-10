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
	const rows = await query<InventorySnapshotView & { total: number }>(client, `
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
		select *,count(*) over()::int total from latest
		order by sku,location_code limit $5 offset $6`,
	[...filters, options.pageSize, offset])
	const countRows = await query<{ total: number }>(client, `
		select count(*)::int total from inventory_position_snapshot s
		join inventory_location l on l.id=s.location_id and l.tenant_id=s.tenant_id and l.active
		where s.tenant_id=$1 and ($2::text is null or s.sku=$2)
			and ($3::text is null or l.location_code=$3)
			and not exists (
				select 1 from inventory_position_snapshot newer
				where newer.tenant_id=s.tenant_id and newer.location_id=s.location_id
					and newer.sku=s.sku and (newer.observed_at,newer.id)>(s.observed_at,s.id)
			)`, filters.slice(0, 3))
	const total = countRows[0]?.total ?? 0
	const snapshots = rows.map(({ total: _total, ...row }) => row)
	const counts = snapshots.reduce((result, row) => {
		result[row.freshness] += 1
		return result
	}, { current: 0, stale: 0, partial: 0, unknown: 0 })
	return {
		snapshots,
		pagination: { page: options.page, pageSize: options.pageSize, total },
		freshness: { ...counts, thresholdHours: options.freshHours, ready: total > 0 && counts.stale === 0 && counts.partial === 0 && counts.unknown === 0 },
	}
}
