"use server"

import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { mayManageTenant } from "@/lib/rbac"

function value(form: FormData, key: string) { return String(form.get(key) ?? "").trim() }
function number(form: FormData, key: string) { return Number(value(form, key)) }
function integer(form: FormData, key: string) { const parsed = number(form, key); if (!Number.isInteger(parsed)) throw new Error(`${key} must be an integer.`); return parsed }
function between(name: string, amount: number, min: number, max: number) { if (!Number.isFinite(amount) || amount < min || amount > max) throw new Error(`${name} must be between ${min} and ${max}.`) }

export async function updateClientSettings(form: FormData) {
	const actor = await currentContext()
	if (!mayManageTenant(actor.role)) throw new Error("Only tenant owners and admins can edit client settings.")
	const name = value(form, "name")
	const slug = value(form, "slug").toLowerCase()
	const timezone = value(form, "timezone")
	const automation_enabled = form.get("automationEnabled") === "on"
	const dry_run = form.get("dryRun") === "on"
	const target_acos_default = number(form, "targetAcos") / 100
	const max_change_pct = number(form, "maxChangePct") / 100
	const cooldown_days = integer(form, "cooldownDays")
	const max_changes_per_day = integer(form, "maxChanges")
	const max_budget_increase_per_day = number(form, "maxBudgetIncrease")
	const blast_radius_pct = number(form, "blastRadiusPct") / 100
	const min_bid = number(form, "minBid")
	const max_bid = number(form, "maxBid")
	const max_daily_budget = number(form, "maxDailyBudget")
	const max_data_age_hours = integer(form, "maxDataAgeHours")
	const settlement_lag_days = integer(form, "settlementLagDays")
	if (name.length < 2 || name.length > 100) throw new Error("Client name must be 2–100 characters.")
	if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) throw new Error("Slug may contain lowercase letters, numbers and single hyphens.")
	if (!timezone || timezone.length > 80) throw new Error("A valid timezone is required.")
	between("Target ACOS (%)", target_acos_default * 100, 0.01, 200)
	between("Maximum change (%)", max_change_pct * 100, 0.01, 100)
	between("Cooldown days", cooldown_days, 0, 90)
	between("Daily change limit", max_changes_per_day, 0, 500)
	between("Daily budget-increase cap", max_budget_increase_per_day, 0, 1000000)
	between("Blast radius (%)", blast_radius_pct * 100, 0.01, 100)
	between("Minimum bid", min_bid, 0, 1000000)
	between("Maximum bid", max_bid, min_bid, 1000000)
	between("Maximum daily budget", max_daily_budget, 0, 100000000)
	between("Maximum data age (hours)", max_data_age_hours, 1, 720)
	between("Settlement lag (days)", settlement_lag_days, 0, 30)
	await withTenant(actor.tenantId, async c => {
		const before = await query(c, `select t.name,t.slug,s.timezone,s.automation_enabled,s.dry_run,s.target_acos_default,s.max_change_pct,s.cooldown_days,s.max_changes_per_day,s.max_budget_increase_per_day,s.blast_radius_pct,s.min_bid,s.max_bid,s.max_daily_budget,s.max_data_age_hours,s.settlement_lag_days from tenant t join tenant_settings s on s.tenant_id=t.id where t.id=$1`, [actor.tenantId])
		await query(c, "update tenant set name=$2,slug=$3 where id=$1", [actor.tenantId,name,slug])
		await query(c, `update tenant_settings set timezone=$2,automation_enabled=$3,dry_run=$4,target_acos_default=$5,max_change_pct=$6,cooldown_days=$7,max_changes_per_day=$8,max_budget_increase_per_day=$9,blast_radius_pct=$10,min_bid=$11,max_bid=$12,max_daily_budget=$13,max_data_age_hours=$14,settlement_lag_days=$15 where tenant_id=$1`, [actor.tenantId,timezone,automation_enabled,dry_run,target_acos_default,max_change_pct,cooldown_days,max_changes_per_day,max_budget_increase_per_day,blast_radius_pct,min_bid,max_bid,max_daily_budget,max_data_age_hours,settlement_lag_days])
		const after = {name,slug,timezone,automation_enabled,dry_run,target_acos_default,max_change_pct,cooldown_days,max_changes_per_day,max_budget_increase_per_day,blast_radius_pct,min_bid,max_bid,max_daily_budget,max_data_age_hours,settlement_lag_days}
		await query(c, "insert into audit_log(tenant_id,actor_user_id,action,entity,before,after) values($1,$2,'tenant.settings_updated',$3,$4::jsonb,$5::jsonb)", [actor.tenantId,actor.userId,`tenant:${actor.tenantId}`,JSON.stringify(before[0] ?? {}),JSON.stringify(after)])
	})
	revalidatePath("/", "layout")
	revalidatePath("/settings/client")
}
