"use server"

import { revalidatePath } from "next/cache"
import { query, withTenant } from "@/lib/db"
import { mayManageTenant } from "@/lib/rbac"
import { currentContext } from "@/lib/session"

const REQUIRED = ["sku", "valid_from", "cogs"] as const
const OPTIONAL_DEFAULTS: Record<string, string> = {
	asin: "",
	valid_to: "",
	freight_in: "0",
	amazon_referral_pct: "0.15",
	fba_fee: "0",
	storage_est: "0",
	vat_rate: "0.20",
	currency: "GBP",
	note: "",
}

function cell(value: FormDataEntryValue | null): string {
	return String(value ?? "").trim()
}

function parseCsvLine(line: string): string[] {
	const out: string[] = []
	let current = ""
	let quoted = false
	for (let i = 0; i < line.length; i += 1) {
		const ch = line[i]
		if (ch === '"') {
			if (quoted && line[i + 1] === '"') {
				current += '"'
				i += 1
			} else {
				quoted = !quoted
			}
		} else if (ch === "," && !quoted) {
			out.push(current.trim())
			current = ""
		} else {
			current += ch
		}
	}
	out.push(current.trim())
	return out
}

function isoDate(value: string, field: string): string | null {
	if (!value) return null
	if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`${field} must be YYYY-MM-DD`)
	return value
}

function amount(value: string, field: string): number {
	if (!value) throw new Error(`${field} is required`)
	const n = Number(value)
	if (!Number.isFinite(n) || n < 0) throw new Error(`${field} must be a non-negative number`)
	return n
}

export async function importCostLedger(form: FormData) {
	const actor = await currentContext()
	if (!mayManageTenant(actor.role)) throw new Error("Only owners and admins can import cost ledger rows.")
	const text = cell(form.get("csv"))
	if (!text) throw new Error("Paste a CSV export before importing.")
	const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
	if (lines.length < 2) throw new Error("CSV must include a header and at least one row.")
	const headers = parseCsvLine(lines[0]).map((h) => h.toLowerCase())
	const missing = REQUIRED.filter((name) => !headers.includes(name))
	if (missing.length) throw new Error(`CSV missing required column(s): ${missing.join(", ")}`)
	let imported = 0
	await withTenant(actor.tenantId, async (client) => {
		for (const [index, line] of lines.slice(1).entries()) {
			const values = parseCsvLine(line)
			const raw: Record<string, string> = { ...OPTIONAL_DEFAULTS }
			headers.forEach((header, i) => { raw[header] = values[i] ?? "" })
			const validFrom = isoDate(raw.valid_from, "valid_from")
			if (!validFrom) throw new Error(`line ${index + 2}: valid_from is required`)
			const validTo = isoDate(raw.valid_to, "valid_to")
			if (validTo && validTo <= validFrom) throw new Error(`line ${index + 2}: valid_to must be after valid_from`)
			const sku = raw.sku.trim()
			if (!sku) throw new Error(`line ${index + 2}: sku is required`)
			const currency = (raw.currency || "GBP").toUpperCase()
			if (!/^[A-Z]{3}$/.test(currency)) throw new Error(`line ${index + 2}: currency must be a 3-letter code`)
			if (!validTo) {
				await query(client, "update sku_cost_ledger set valid_to=$3 where tenant_id=$1 and sku=$2 and valid_to is null and valid_from < $3", [actor.tenantId, sku, validFrom])
			}
			await query(client, `insert into sku_cost_ledger (tenant_id,sku,asin,valid_from,valid_to,cogs,freight_in,amazon_referral_pct,fba_fee,storage_est,vat_rate,currency,note) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) on conflict (tenant_id, sku) where valid_to is null do update set asin=excluded.asin, valid_from=excluded.valid_from, cogs=excluded.cogs, freight_in=excluded.freight_in, amazon_referral_pct=excluded.amazon_referral_pct, fba_fee=excluded.fba_fee, storage_est=excluded.storage_est, vat_rate=excluded.vat_rate, currency=excluded.currency, note=excluded.note`, [actor.tenantId, sku, raw.asin || null, validFrom, validTo, amount(raw.cogs, "cogs"), amount(raw.freight_in, "freight_in"), amount(raw.amazon_referral_pct, "amazon_referral_pct"), amount(raw.fba_fee, "fba_fee"), amount(raw.storage_est, "storage_est"), amount(raw.vat_rate, "vat_rate"), currency, raw.note || null])
			imported += 1
		}
		await query(client, "insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'economics.cost_ledger_imported',$3,$4::jsonb)", [actor.tenantId, actor.userId, `tenant:${actor.tenantId}`, JSON.stringify({ imported })])
	})
	revalidatePath("/economics")
}
