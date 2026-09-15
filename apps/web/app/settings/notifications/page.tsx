import { SettingsCard, SettingsHeading, StatusPill } from "@/components/settings-ui"
import { withTenant } from "@/lib/db"
import {
	notificationDeliverySummary,
	type NotificationDeliverySummary,
} from "@/lib/notifications"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

const CHANNELS = [
	{
		id: "in_app",
		name: "In-app",
		active: true,
		description: "Delivered transactionally into the existing History alert inbox.",
	},
	{
		id: "email",
		name: "Email",
		active: false,
		description: "Blocked until router preferences, consent, templates, and a provider adapter exist.",
	},
	{
		id: "whatsapp",
		name: "WhatsApp",
		active: false,
		description: "Blocked until explicit consent, templates, and a configured provider adapter exist.",
	},
	{
		id: "sms",
		name: "SMS",
		active: false,
		description: "Blocked until explicit consent, templates, and a configured provider adapter exist.",
	},
] as const

function activity(rows: NotificationDeliverySummary[], channel: string) {
	const matching = rows.filter((row) => row.channel === channel)
	return {
		count: matching.reduce((sum, row) => sum + row.delivery_count, 0),
		cost: matching.reduce((sum, row) => sum + Number(row.cost_amount), 0),
		statuses: matching.map((row) => `${row.status}: ${row.delivery_count}`),
	}
}

export default async function NotificationSettingsPage() {
	const tenantId = await currentTenantId()
	const summary = await withTenant(tenantId, notificationDeliverySummary)

	return (
		<div>
			<SettingsHeading
				title="Notification Router"
				description="Tenant-scoped delivery state from the canonical notification audit. This page is read-only."
			/>
			<div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
				External delivery is not enabled. Provider credentials alone do not make a channel ready.
			</div>
			<div className="grid gap-4 md:grid-cols-2">
				{CHANNELS.map((channel) => {
					const state = activity(summary, channel.id)
					return (
						<SettingsCard
							key={channel.id}
							title={channel.name}
							aside={
								<StatusPill ready={channel.active}>
									{channel.active ? "Active" : "Blocked configuration"}
								</StatusPill>
							}
						>
							<p className="text-sm text-slate-600">{channel.description}</p>
							<div className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500">
								<div>{state.count} audited delivery records</div>
								<div>Recorded cost: {state.cost.toFixed(2)}</div>
								<div>{state.statuses.length ? state.statuses.join(" · ") : "No delivery activity"}</div>
							</div>
						</SettingsCard>
					)
				})}
			</div>
		</div>
	)
}
