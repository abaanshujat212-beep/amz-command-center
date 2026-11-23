import { query, withTenant } from "@/lib/db"
import { OPERATOR_ALERT_KINDS, presentOperatorAlert, type AlertFilters, type OperatorAlertRow } from "@/lib/operator-alerts-contract"

export async function loadOperatorAlerts(tenantId: string, filters: AlertFilters) {
	const { limit, severity } = filters
	return withTenant(tenantId, async client => {
		// This is a read-only presentation of the existing alert inbox. The
		// explicit tenant predicates supplement the connection's forced RLS.
		// Do not select notification payload, title, or entity reference: these
		// can contain upstream identifiers, diagnostic text, or credentials.
		const rows = await query<OperatorAlertRow>(client, `
			select a.id::text, a.kind, a.severity,
			       coalesce(e.occurred_at, a.created_at) as occurred_at, e.source
			  from alert a
			  left join notification_event e
			    on e.id = a.notification_event_id and e.tenant_id = a.tenant_id
			 where a.tenant_id = $1 and a.resolved_at is null and a.kind = any($2::text[])
			   and ($3::text is null or a.severity = $3)
			 order by case a.severity when 'critical' then 0 when 'warning' then 1 else 2 end,
			          coalesce(e.occurred_at, a.created_at) desc, a.id desc
			 limit $4`, [tenantId, OPERATOR_ALERT_KINDS, severity, limit + 1])
		return {
			tenantId,
			scope: "tenant" as const,
			severity,
			shownThrough: new Date().toISOString(),
			hasMore: rows.length > limit,
			items: rows.slice(0, limit).flatMap(row => {
				const item = presentOperatorAlert(row)
				return item ? [item] : []
			}),
		}
	})
}
