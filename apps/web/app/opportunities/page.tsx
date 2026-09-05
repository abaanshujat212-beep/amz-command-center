import { withTenant } from "@/lib/db"
import { count, money, percent, stamp } from "@/lib/format"
import { productOpportunities } from "@/lib/queries"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export default async function Opportunities({ searchParams }: { searchParams: Promise<{ minScore?: string }> }) {
	const params = await searchParams
	const minScore = Math.max(0, Math.min(100, Number(params.minScore ?? 0) || 0))
	const rows = await withTenant(await currentTenantId(), (c) => productOpportunities(c, minScore))
	return <div className="space-y-4"><div><h1 className="text-lg font-semibold">Product opportunities</h1><p className="text-sm text-slate-600">Keepa, traffic and SKU economics combined. Missing economics lowers confidence rather than inventing margin.</p></div>
		<form className="flex items-end gap-2"><label className="text-sm">Minimum score<input name="minScore" type="number" min="0" max="100" defaultValue={minScore} className="ml-2 w-20 rounded border px-2 py-1" /></label><button className="rounded bg-slate-900 px-3 py-1 text-sm text-white">Filter</button></form>
		<div className="overflow-x-auto rounded border bg-white"><table className="w-full text-sm"><thead><tr className="border-b text-left text-xs uppercase text-slate-500"><th className="p-3">Score / product</th><th className="p-3">Keepa</th><th className="p-3 num">30d sales</th><th className="p-3 num">Margin</th><th className="p-3">Status</th></tr></thead><tbody>{rows.map(r => <tr key={r.asin} className="border-b align-top"><td className="p-3"><b>{r.opportunity_score}</b> · {r.title ?? r.asin}<div className="text-xs text-slate-500">{r.asin} {r.sku ? `· ${r.sku}` : ""} {r.brand ? `· ${r.brand}` : ""}</div></td><td className="p-3">{money(r.buy_box_price)} · rank {count(r.sales_rank)}<div className="text-xs text-slate-500">{count(r.review_count)} reviews · {r.rating ?? "—"}★ · {count(r.offer_count)} offers</div></td><td className="p-3 num">{money(r.sales_30d)}<div className="text-xs text-slate-500">{count(r.units_30d)} units</div></td><td className="p-3 num">{percent(r.contribution_margin_pct)}<div className="text-xs text-slate-500">BE ACOS {percent(r.break_even_acos)}</div></td><td className={r.economics_incomplete ? "p-3 tone-warn" : "p-3 tone-good"}>{r.economics_incomplete ? "costs missing" : "costed"}<div className="text-xs text-slate-500">Keepa {stamp(r.keepa_captured_at)}</div></td></tr>)}</tbody></table></div>
		{rows.length === 0 && <p className="rounded border bg-white p-6 text-sm text-slate-600">No products match this score. Run Sales &amp; Traffic, Keepa ingestion and dbt build.</p>}</div>
}
