import { withTenant } from "@/lib/db"
import { money, percent } from "@/lib/format"
import { mayManageTenant } from "@/lib/rbac"
import { skuEconomics } from "@/lib/queries"
import { currentContext } from "@/lib/session"
import { importCostLedger } from "./actions"

export const dynamic = "force-dynamic"

const sample = `sku,asin,valid_from,cogs,freight_in,amazon_referral_pct,fba_fee,storage_est,vat_rate,currency,note
SKU-001,B0EXAMPLE,2026-09-01,8.50,0.75,0.15,3.10,0.20,0.20,GBP,initial sandbox cost`

export default async function Economics() {
	const actor = await currentContext()
	const editable = mayManageTenant(actor.role)
	const rows = await withTenant(actor.tenantId, c => skuEconomics(c))
	return <div className="space-y-4"><div><h1 className="text-lg font-semibold">SKU economics</h1><p className="text-sm text-slate-600">Cost ledger status, contribution margin and break-even ACOS.</p></div><div className="rounded border border-blue-200 bg-blue-50 p-3 text-sm"><b>Import or update costs:</b> paste a CSV below or run <code>python -m services.economics.cost_import your-file.csv --tenant-id {actor.tenantId}</code>, then run <code>make dbt</code> so marts pick up the new economics.</div><form action={importCostLedger} className="rounded border bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-medium">Browser cost import</h2><p className="text-sm text-slate-600">Validated tenant-scoped import for the same fields as the CLI importer.</p></div>{!editable && <span className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">Read-only role</span>}</div><textarea name="csv" disabled={!editable} defaultValue={sample} rows={6} className="mt-3 w-full rounded border px-3 py-2 font-mono text-xs disabled:bg-slate-100"/><div className="mt-3 flex flex-wrap items-center gap-3"><button disabled={!editable} className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:bg-slate-300">Import costs</button><p className="text-xs text-slate-500">Required: sku, valid_from, cogs. Open SKU windows are safely replaced; historical closed windows stay intact.</p></div></form><div className="overflow-x-auto rounded border bg-white"><table className="w-full text-sm"><thead><tr className="border-b text-left text-xs uppercase text-slate-500"><th className="p-3">SKU / ASIN</th><th className="p-3 num">Price</th><th className="p-3 num">COGS</th><th className="p-3 num">Unit cost</th><th className="p-3 num">Contribution</th><th className="p-3 num">Break-even ACOS</th><th className="p-3">Status</th></tr></thead><tbody>{rows.map(r => <tr key={r.sku} className="border-b"><td className="p-3 font-medium">{r.sku}<div className="text-xs text-slate-500">{r.asin ?? "ASIN missing"}</div></td><td className="p-3 num">{money(r.avg_price)}</td><td className="p-3 num">{money(r.cogs)}</td><td className="p-3 num">{money(r.total_unit_cost)}</td><td className="p-3 num">{money(r.contribution_margin)}<div className="text-xs text-slate-500">{percent(r.contribution_margin_pct)}</div></td><td className="p-3 num">{percent(r.break_even_acos)}</td><td className={r.economics_incomplete ? "p-3 tone-warn" : "p-3 tone-good"}>{r.economics_incomplete ? "incomplete" : "ready"}</td></tr>)}</tbody></table></div></div>
}
