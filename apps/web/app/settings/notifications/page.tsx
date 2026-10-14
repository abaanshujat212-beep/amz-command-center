import { SettingsCard, SettingsHeading, StatusPill } from "@/components/settings-ui"
import { withTenant } from "@/lib/db"
import { notificationDeliveryAudit, notificationDeliverySummary, notificationProviderStates, notificationRoutePreferences, notificationTemplates } from "@/lib/notifications"
import { currentContext } from "@/lib/session"
import { saveNotificationRoute, saveNotificationTemplate } from "./actions"

export const dynamic = "force-dynamic"
const CHANNELS = ["email", "whatsapp", "sms"] as const
const input = "w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"

export default async function NotificationSettingsPage() {
	const actor = await currentContext()
	const data = await withTenant(actor.tenantId, async c => ({
		summary: await notificationDeliverySummary(c), preferences: await notificationRoutePreferences(c),
		providers: await notificationProviderStates(c), deliveries: await notificationDeliveryAudit(c), templates: await notificationTemplates(c),
	}))
	const editable = actor.role === "owner" || actor.role === "admin"
	return <div>
		<SettingsHeading title="Notification Router" description="One tenant-scoped inbox with governed opt-in routes, templates, retries and delivery cost evidence." />
		<div className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">In-app delivery works without Amazon or external credentials. External sends remain blocked until route, consent, approved template and verified provider readiness all pass.</div>
		<div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
			<SettingsCard title="In-app" aside={<StatusPill ready>Always active</StatusPill>}><p className="text-sm text-slate-600">Immediate delivery into History. Cannot be disabled.</p></SettingsCard>
			{CHANNELS.map(channel => {
				const pref=data.preferences.find(p=>p.channel===channel&&p.event_type==="*"), provider=data.providers.find(p=>p.channel===channel)
				const ready=Boolean(pref?.enabled)&&provider?.readiness_state==="READY"
				return <SettingsCard key={channel} title={channel==="sms"?"SMS":channel[0].toUpperCase()+channel.slice(1)} aside={<StatusPill ready={ready}>{ready?"Eligible":"Blocked"}</StatusPill>}>
					<p className="mb-3 text-xs text-slate-500">Provider: {provider?.readiness_state??"BLOCKED_CONFIGURATION"}{provider?.readiness_reason?` · ${provider.readiness_reason}`:""}</p>
					<form action={saveNotificationRoute} className="space-y-3"><input type="hidden" name="channel" value={channel}/><input type="hidden" name="eventType" value="*"/>
						<label className="flex items-center gap-2 text-sm"><input type="checkbox" name="enabled" defaultChecked={pref?.enabled}/><span>Opt in to this route</span></label>
						<div className="grid grid-cols-2 gap-2"><select className={input} name="deliveryMode" defaultValue={pref?.delivery_mode??"immediate"}><option value="immediate">Immediate</option><option value="digest">Digest</option></select><select className={input} name="digestInterval" defaultValue={pref?.digest_interval_minutes??1440}><option value="60">Hourly</option><option value="1440">Daily</option></select></div>
						<input className={input} name="timezone" defaultValue={pref?.timezone??"Europe/London"} aria-label="IANA timezone"/><div className="grid grid-cols-2 gap-2"><input aria-label="Quiet hours start" className={input} type="time" name="quietStart" defaultValue={pref?.quiet_start?.slice(0,5)}/><input aria-label="Quiet hours end" className={input} type="time" name="quietEnd" defaultValue={pref?.quiet_end?.slice(0,5)}/></div>
						<label className="flex items-center gap-2 text-xs"><input type="checkbox" name="criticalBypass" defaultChecked={pref?.critical_bypass}/><span>Critical may bypass quiet hours only</span></label><button disabled={!editable} className="rounded-lg bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-40">Save route</button>
					</form>
				</SettingsCard>
			})}
		</div>
		<div className="mt-6"><SettingsCard title="Approved message templates"><p className="mb-4 text-sm text-slate-500">Templates expose only named scalar variables. Provider-specific approval remains required where applicable.</p>
			<form action={saveNotificationTemplate} className="grid gap-3 md:grid-cols-2"><select className={input} name="channel">{CHANNELS.map(c=><option key={c}>{c}</option>)}</select><input className={input} name="eventType" defaultValue="*"/><input className={input} name="locale" defaultValue="en-GB"/><input className={input} name="subject" placeholder="Email subject (optional)"/><textarea className={`${input} md:col-span-2`} name="body" required placeholder="${title}: ${summary}"/><input className={input} name="variables" placeholder="title, summary"/><label className="flex items-center gap-2 text-sm"><input name="approved" type="checkbox"/><span>Approve for delivery</span></label><button disabled={!editable} className="w-fit rounded-lg bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-40">Save template</button></form>
			{data.templates.length>0&&<div className="mt-4 text-xs text-slate-500">{data.templates.map(t=><div key={t.id}>{t.channel} · {t.event_type} · {t.locale} · {t.status}</div>)}</div>}
		</SettingsCard></div>
		<div className="mt-6"><SettingsCard title="Delivery audit, retries and cost"><div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b text-slate-500"><th className="py-2">Event</th><th>Channel</th><th>Status / policy</th><th>Attempts</th><th>Next / DLQ</th><th>Cost</th></tr></thead><tbody>{data.deliveries.map(d=><tr key={d.id} className="border-b border-slate-100"><td className="py-2 pr-3">{d.title}</td><td>{d.channel}</td><td>{d.status} · {d.policy_decision}</td><td>{d.attempt}/{d.max_attempts}</td><td>{d.dead_lettered_at?"Dead letter":d.next_attempt_at??"—"}</td><td>{Number(d.cost_amount).toFixed(4)} {d.cost_currency??""}</td></tr>)}</tbody></table>{!data.deliveries.length&&<p className="py-4 text-slate-500">No delivery records yet.</p>}</div><p className="mt-3 text-xs text-slate-500">{data.summary.reduce((n,r)=>n+r.delivery_count,0)} total channel records. Retry evidence and verified callbacks are append-only.</p></SettingsCard></div>
	</div>
}
