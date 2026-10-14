"use server"
import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
const CHANNELS = new Set(["email", "whatsapp", "sms"]), MODES = new Set(["immediate", "digest"])
const EVENT_TYPES = new Set(["*","auth_expiring","auth_expired","pipeline_failed","data_stale","blast_radius_halt","budget_guard","action_failed","economics_incomplete","low_inventory","projected_stockout","reorder_due","inbound_delayed","excess_stock","unusual_demand","report_ready","product_opportunity_digest"])
function value(form: FormData, key: string) { return String(form.get(key) ?? "").trim() }
function permitted(role: string) { if (role !== "owner" && role !== "admin") throw new Error("Only owners and admins can manage notification routes.") }
export async function saveNotificationRoute(form: FormData) {
	const actor = await currentContext(); permitted(actor.role)
	const channel=value(form,"channel"), eventType=value(form,"eventType")||"*", mode=value(form,"deliveryMode")||"immediate", timezone=value(form,"timezone")||"UTC"
	if(!CHANNELS.has(channel)||!EVENT_TYPES.has(eventType)||!MODES.has(mode)||timezone.length>64) throw new Error("Invalid notification route.")
	const enabled=form.get("enabled")==="on", quietStart=value(form,"quietStart")||null, quietEnd=value(form,"quietEnd")||null
	if((quietStart===null)!==(quietEnd===null)) throw new Error("Quiet hours need both start and end.")
	const digest=mode==="digest"?Number(value(form,"digestInterval")):null
	if(mode==="digest"&&digest!==60&&digest!==1440) throw new Error("Digest interval must be hourly or daily.")
	const criticalBypass=form.get("criticalBypass")==="on", after={eventType,channel,enabled,mode,digest,timezone,quietStart,quietEnd,criticalBypass}
	await withTenant(actor.tenantId,async c=>{ await query(c,`insert into notification_route_preference (tenant_id,event_type,channel,enabled,delivery_mode,digest_interval_minutes,timezone,quiet_start,quiet_end,critical_bypass,updated_at) values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,now()) on conflict(tenant_id,event_type,channel) do update set enabled=excluded.enabled,delivery_mode=excluded.delivery_mode,digest_interval_minutes=excluded.digest_interval_minutes,timezone=excluded.timezone,quiet_start=excluded.quiet_start,quiet_end=excluded.quiet_end,critical_bypass=excluded.critical_bypass,updated_at=now()`,[actor.tenantId,eventType,channel,enabled,mode,digest,timezone,quietStart,quietEnd,criticalBypass]); await query(c,"insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'notification.route_saved',$3,$4::jsonb)",[actor.tenantId,actor.userId,`notification-route:${eventType}:${channel}`,JSON.stringify(after)]) })
	revalidatePath("/settings/notifications")
}
export async function saveNotificationTemplate(form: FormData) {
	const actor=await currentContext(); permitted(actor.role)
	const channel=value(form,"channel"),eventType=value(form,"eventType")||"*",locale=value(form,"locale")||"en-GB",subject=value(form,"subject")||null,body=value(form,"body"),approve=form.get("approved")==="on",variables=value(form,"variables").split(",").map(v=>v.trim()).filter(Boolean)
	if(!CHANNELS.has(channel)||!EVENT_TYPES.has(eventType)||!/^[a-z]{2}(-[A-Z]{2})?$/.test(locale)||!body||body.length>10000||variables.some(v=>!/^[a-z][a-z0-9_]*$/.test(v))) throw new Error("Invalid template content.")
	const status=approve?"APPROVED":"DRAFT"
	await withTenant(actor.tenantId,async c=>{ await query(c,`insert into notification_template (tenant_id,event_type,channel,locale,status,subject_template,body_template,variable_allowlist,created_by,approved_by,approved_at) values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,case when $5='APPROVED' then now() end) on conflict(tenant_id,event_type,channel,locale) do update set status=excluded.status,subject_template=excluded.subject_template,body_template=excluded.body_template,variable_allowlist=excluded.variable_allowlist,approved_by=excluded.approved_by,approved_at=excluded.approved_at,updated_at=now()`,[actor.tenantId,eventType,channel,locale,status,subject,body,variables,actor.userId,approve?actor.userId:null]); await query(c,"insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'notification.template_saved',$3,$4::jsonb)",[actor.tenantId,actor.userId,`notification-template:${eventType}:${channel}:${locale}`,JSON.stringify({eventType,channel,locale,status,variables})]) })
	revalidatePath("/settings/notifications")
}
