import type { PoolClient } from "pg"
import { query } from "@/lib/db"
import { forecastInventory, type InventoryForecastInput } from "@/lib/inventory-forecast-engine"

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

export type InventoryDemandVelocityWindow = {
	windowDays: 7 | 14 | 30
	startDay: string
	endDay: string
	observedDays: number
	missingDays: number
	coverage: number
	status: "complete" | "partial" | "no_data" | "invalid"
	unitsObserved: number | null
	averageDailyUnitsObserved: number | null
	invalidRows: number
	numericRangeExceeded: boolean
	salesFreshness: "current" | "stale" | "unknown"
	salesLoadedAt: string | null
	latestSalesDate: string | null
}

export async function inventoryForecastRead(client: PoolClient, tenantId: string, freshHours: number) {
	const rows = await query<{
		sku: string; available_qty: number | null; observed_at: string; freshness_state: string;
		average_daily_demand: number | null; observed_days: number; loaded_at: string;
		demand_history: { day: string; units: number }[];
		invalid_demand_rows: number; sales_freshness: "current" | "stale" | "unknown";
		latest_sales_date: string | null; numeric_range_exceeded: boolean;
		velocity_windows: Record<"7d" | "14d" | "30d", InventoryDemandVelocityWindow>;
	}>(client, `
		with forecast_clock as (
			select (now() at time zone 'UTC')::date as as_of_day
		), latest_position as (
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
				case when coalesce(record->>'units_ordered',record->>'unitsOrdered') ~ '^[0-9]{1,16}$'
					then coalesce(record->>'units_ordered',record->>'unitsOrdered')::numeric
					else null end units_ordered,
				loaded_at
			from raw.raw_sales_traffic_asin_daily
			where tenant_id=$1 and report_date >= (select as_of_day from forecast_clock)-30
				and report_date < (select as_of_day from forecast_clock)
				and coalesce(record->>'sku',record->>'sellerSku') is not null
		), daily_sales as (
			select sku,report_date,
				case when count(*) filter (where units_ordered is null) > 0 then null
					else sum(units_ordered) end units_ordered,
				count(*) filter (where units_ordered is null)::int invalid_rows,
				max(loaded_at) loaded_at,bool_or(loaded_at > now()) future_load
			from sales group by sku,report_date
		), demand_by_sku as (
			select sku,
				case when sum(invalid_rows) > 0 or sum(units_ordered) > 9007199254740991 then null
					else sum(units_ordered) / count(*) end average_daily_demand,
				count(*)::int observed_days,sum(invalid_rows)::int invalid_demand_rows,
				coalesce(sum(units_ordered) > 9007199254740991,false) numeric_range_exceeded,
				max(report_date) latest_sales_date,
				max(loaded_at) loaded_at,bool_or(future_load) future_load,
				jsonb_agg(jsonb_build_object('day',report_date::text,'units',units_ordered) order by report_date)
					filter (where invalid_rows=0 and units_ordered is not null) demand_history
			from daily_sales group by sku
		), velocity_window_stats as (
			select p.sku,w.window_days,c.as_of_day,
				count(d.report_date)::int observed_days,coalesce(sum(d.invalid_rows),0)::int invalid_rows,
				sum(d.units_ordered) units_observed,
				coalesce(sum(d.units_ordered) > 9007199254740991,false) numeric_range_exceeded,
				max(d.loaded_at) loaded_at,max(d.report_date) latest_sales_date,
				coalesce(bool_or(d.future_load),false) future_load
			from position_by_sku p cross join (values(7),(14),(30)) w(window_days)
			cross join forecast_clock c left join daily_sales d on d.sku=p.sku
				and d.report_date >= c.as_of_day-w.window_days and d.report_date < c.as_of_day
			group by p.sku,w.window_days,c.as_of_day
		), velocity_by_sku as (
			select sku,jsonb_object_agg(window_days::text || 'd',jsonb_build_object(
				'windowDays',window_days,'startDay',(as_of_day-window_days)::text,'endDay',(as_of_day-1)::text,
				'observedDays',observed_days,'missingDays',window_days-observed_days,
				'coverage',round(observed_days::numeric/window_days,4),
				'status',case when invalid_rows > 0 or numeric_range_exceeded then 'invalid'
					when observed_days=window_days then 'complete' when observed_days>0 then 'partial' else 'no_data' end,
				'unitsObserved',case when invalid_rows > 0 or numeric_range_exceeded then null else units_observed end,
				'averageDailyUnitsObserved',case when invalid_rows > 0 or numeric_range_exceeded then null
					else units_observed/nullif(observed_days,0) end,
				'invalidRows',invalid_rows,'numericRangeExceeded',numeric_range_exceeded,
				'salesFreshness',case when loaded_at is null or future_load then 'unknown'
					when loaded_at < now()-($2::int*interval '1 hour') then 'stale' else 'current' end,
				'salesLoadedAt',to_char(loaded_at at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
				'latestSalesDate',latest_sales_date::text
			)) velocity_windows from velocity_window_stats group by sku
		)
		select p.sku,p.available_qty,p.observed_at::text observed_at,
			case when p.source_unknown then 'unknown'
				when p.source_stale then 'stale'
				when p.source_partial then 'partial'
				else 'current' end freshness_state,
			d.average_daily_demand,coalesce(d.observed_days,0)::int observed_days,
			coalesce(d.numeric_range_exceeded,false) numeric_range_exceeded,v.velocity_windows,
			coalesce(d.invalid_demand_rows,0)::int invalid_demand_rows,
			d.latest_sales_date::text latest_sales_date,d.demand_history,
			case when d.loaded_at is null or d.future_load then 'unknown'
				when d.loaded_at < now()-($2::int*interval '1 hour') then 'stale'
				else 'current' end sales_freshness,
			coalesce(d.loaded_at::text,'') loaded_at
		from position_by_sku p left join demand_by_sku d using(sku)
		join velocity_by_sku v using(sku) order by p.sku`, [tenantId, freshHours])
	return rows.map(row => {
		const asOf = new Date().toISOString().slice(0, 10)
		const input: InventoryForecastInput = {
			sku: row.sku, asOf, observedAt: row.observed_at.slice(0, 10), source: "multi_location_inventory",
			demand: row.demand_history ?? [], position: { availableNow: row.available_qty },
			leadTimeDays: null, leadTimeSamples: 0, seasonalIndices: {},
			staleAfterDays: Math.floor(freshHours / 24), minimumHistoryDays: 14,
			partialSource: row.freshness_state === "partial" || row.freshness_state === "unknown" || row.freshness_state === "stale",
		}
		const forecast = forecastInventory(input)
		const blockers = [...forecast.blockers]
		if (row.available_qty === null) blockers.push("available_now_unknown")
		if (row.freshness_state === "unknown" || row.freshness_state === "stale") blockers.push(`inventory_${row.freshness_state}`)
		if (row.observed_days < 30) blockers.push("incomplete_demand_history")
		if (row.invalid_demand_rows > 0) blockers.push("invalid_demand_history")
		if (row.numeric_range_exceeded) blockers.push("demand_numeric_range_exceeded")
		if (row.sales_freshness !== "current") blockers.push(`sales_${row.sales_freshness}`)
		return {
			...forecast, blockers: [...new Set(blockers)],
			daysOfSupply: forecast.daysOfSupplyNow,
			status: blockers.length ? (forecast.status === "blocked" ? "blocked" : "reduced_confidence") : forecast.status,
			confidence: blockers.length ? 0 : forecast.confidence,
			assumptions: { ...forecast.assumptions, demandWindowDays: 30, observedSalesDays: row.observed_days,
				missingSalesDays: 30 - row.observed_days, demandAverageMethod: "observed_days",
				invalidDemandRows: row.invalid_demand_rows, salesFreshness: row.sales_freshness,
				latestSalesDate: row.latest_sales_date, salesLoadedAt: row.loaded_at || null,
				inventoryObservedAt: row.observed_at,
				seasonality: "not_applied", leadTime: "not_configured" },
		}
	})
}
