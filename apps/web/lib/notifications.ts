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

export type NotificationRoutePreference = {
	event_type: string; channel: string; enabled: boolean
	delivery_mode: "immediate" | "digest"; digest_interval_minutes: number | null
	timezone: string; quiet_start: string | null; quiet_end: string | null; critical_bypass: boolean
}
export async function notificationRoutePreferences(client: PoolClient) {
	return query<NotificationRoutePreference>(client, `select event_type,channel,enabled,delivery_mode,digest_interval_minutes,timezone,quiet_start::text,quiet_end::text,critical_bypass from notification_route_preference order by channel,event_type`)
}
export type NotificationProviderState = { channel: string; readiness_state: string; readiness_reason: string | null; evidence_expires_at: string | null }
export async function notificationProviderStates(client: PoolClient) {
	return query<NotificationProviderState>(client, `select channel,readiness_state,readiness_reason,evidence_expires_at::text from notification_provider_state order by channel`)
}
export type NotificationDeliveryAudit = { id: string; title: string; channel: string; status: string; policy_decision: string; attempt: number; max_attempts: number; next_attempt_at: string | null; dead_lettered_at: string | null; cost_amount: number; cost_currency: string | null; updated_at: string }
export async function notificationDeliveryAudit(client: PoolClient, limit = 25) {
	return query<NotificationDeliveryAudit>(client, `select d.id::text,e.title,d.channel,d.status,d.policy_decision,d.attempt,d.max_attempts,d.next_attempt_at::text,d.dead_lettered_at::text,d.cost_amount,d.cost_currency,d.updated_at::text from notification_delivery d join notification_event e on e.id=d.event_id and e.tenant_id=d.tenant_id order by d.updated_at desc limit $1`, [limit])
}
export type NotificationTemplate = { id: string; event_type: string; channel: string; locale: string; status: string; subject_template: string | null; body_template: string; variable_allowlist: string[] }
export async function notificationTemplates(client: PoolClient) {
	return query<NotificationTemplate>(client, `select id::text,event_type,channel,locale,status,subject_template,body_template,variable_allowlist from notification_template order by channel,event_type,locale`)
}
