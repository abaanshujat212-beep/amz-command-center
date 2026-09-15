import type { PoolClient } from "pg"
import { query } from "./db"

export type NotificationAlert = {
	id: string
	kind: string
	severity: string
	title: string
	entity_ref: string | null
	created_at: string
	detail: unknown
	notification_source: string | null
	in_app_status: string | null
}

export async function notificationAlerts(
	client: PoolClient,
	limit = 20,
): Promise<NotificationAlert[]> {
	return query<NotificationAlert>(
		client,
		`select a.id::text, a.kind, a.severity, a.title, a.entity_ref,
		        a.created_at::text, a.detail, e.source as notification_source,
		        d.status as in_app_status
		   from alert a
		   left join notification_event e
		     on e.id = a.notification_event_id and e.tenant_id = a.tenant_id
		   left join notification_delivery d
		     on d.event_id = e.id and d.tenant_id = a.tenant_id and d.channel = 'in_app'
		  where a.resolved_at is null
		  order by case a.severity when 'critical' then 0 when 'warning' then 1 else 2 end,
		           a.created_at desc
		  limit $1`,
		[limit],
	)
}

export type NotificationDeliverySummary = {
	channel: string
	status: string
	delivery_count: number
	cost_amount: number
}

export async function notificationDeliverySummary(
	client: PoolClient,
): Promise<NotificationDeliverySummary[]> {
	return query<NotificationDeliverySummary>(
		client,
		`select channel, status, count(*)::int as delivery_count,
		        coalesce(sum(cost_amount), 0) as cost_amount
		   from notification_delivery
		  group by channel, status
		  order by channel, status`,
	)
}
