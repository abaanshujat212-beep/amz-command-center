import { randomUUID } from "node:crypto"
import { query, withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { canDraftPO, canManagePO } from "@/lib/purchase-orders"
import { approveSupplierForPO, changePO, createPO } from "./actions"

export const dynamic = "force-dynamic"
const input = "rounded border border-slate-200 px-3 py-2 text-sm"
const button = "w-fit rounded bg-slate-900 px-4 py-2 text-sm text-white"
type Order = { id:string; supplier_name:string; product_name:string; product_sku:string; quote_ref:string; quote_version:number; quantity:string; unit_price:string; total:string; currency:string; state:string }
type Quote = { id:string; quote_ref:string; version:number; supplier:string; product:string; moq:string|null }

export default async function PurchaseOrders({searchParams}:{searchParams:Promise<{error?:string}>}) {
	const a=await currentContext()
	const {error}=await searchParams
	const {orders,quotes,prospects}=await withTenant(a.tenantId,async c=>{
		const orders=await query<Order>(c,`select id, supplier_name, product_name,product_sku, quote_ref, quote_version,
			quantity::text,unit_price::text,total::text,currency,state from supplier_purchase_order
			where tenant_id=$1 order by created_at desc,id limit 100`,[a.tenantId])
		const quotes=canDraftPO(a.role)?await query<Quote>(c,`select q.id,q.quote_ref,q.version,t.display_name supplier,p.product_name product,coalesce(q.moq,p.moq)::text moq
			from supplier_quote q join supplier_profile s on s.tenant_id=q.tenant_id and s.party_id=q.supplier_party_id
			join party t on t.tenant_id=q.tenant_id and t.id=q.supplier_party_id
			join supplier_product p on p.tenant_id=q.tenant_id and p.id=q.supplier_product_id
			where q.tenant_id=$1 and q.superseded_at is null and q.quoted_on<=current_date and (q.valid_until is null or q.valid_until>=current_date)
			and p.active and s.status in ('prospect','approved') order by q.quoted_on desc,q.id limit 200`,[a.tenantId]):[]
		const prospects=canManagePO(a.role)?await query<{id:string;name:string}>(c,`select t.id,t.display_name name from supplier_profile s
			join party t on t.tenant_id=s.tenant_id and t.id=s.party_id
			where s.tenant_id=$1 and s.status='prospect' order by t.display_name,t.id limit 200`,[a.tenantId]):[]
		return {orders,quotes,prospects}
	})
	return <div className="space-y-6">
		<header><a href="/suppliers" className="text-sm underline">Supplier workspace</a>
			<h1 className="text-lg font-semibold">Purchase orders</h1>
			<p className="text-sm text-slate-600">Single-line orders from existing quotes. Issuing records an internal decision only. It does not contact suppliers, place an external order, record receipts, or change inventory.</p>
		</header>
		{typeof error==="string"&&<p role="alert" className="rounded bg-amber-50 p-3 text-sm">{error.slice(0,180)}</p>}
		{canDraftPO(a.role)&&<form action={createPO} className="grid gap-3 rounded border p-4">
			<h2 className="font-medium">Draft from quote</h2>
			<input type="hidden" name="id" value={randomUUID()}/>
			<label className="grid gap-1 text-sm">Current quote<select className={input} name="quote" required>
				<option value="">Select a quote</option>{quotes.map(q=><option key={q.id} value={q.id}>{q.supplier} · {q.product} · {q.quote_ref} v{q.version}{q.moq?` · minimum ${q.moq}`:""}</option>)}
			</select></label>
			<label className="grid gap-1 text-sm">Quantity<input className={input} name="quantity" type="number" min="0.0001" max="99999999.9999" step="0.0001" required/></label>
			<button className={button} disabled={!quotes.length}>Create draft</button>
		</form>}
		{prospects.length>0&&<form action={approveSupplierForPO} className="grid gap-3 rounded border p-4">
			<label className="grid gap-1 text-sm">Approve a prospect for purchasing<select className={input} name="supplier" required>
				<option value="">Select a supplier</option>{prospects.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}
			</select></label>
			<button className={button}>Approve supplier</button>
		</form>}
		<section className="space-y-3"><h2 className="font-medium">Recent orders</h2>
			{!orders.length&&<p className="text-sm text-slate-600">No purchase orders yet.</p>}
			{orders.map(o=><article key={o.id} className="space-y-2 rounded border p-3">
				<h3 className="font-medium">{o.supplier_name} · {o.product_name}</h3>
				<a href={`/suppliers/purchase-orders/${o.id}`} className="text-sm underline">View receiving reviews</a>
				<p className="text-sm">{o.state} · {o.product_sku} · Quote {o.quote_ref} v{o.quote_version}</p>
				<p className="text-sm">{o.quantity} × {o.currency} {o.unit_price} = {o.currency} {o.total} before freight or other charges</p>
				{canManagePO(a.role)&&o.state!=="cancelled"&&<form action={changePO} className="flex flex-wrap gap-2">
					<input type="hidden" name="id" value={o.id}/>
					<input type="hidden" name="from" value={o.state}/>
					{o.state==="draft"&&<button name="to" value="issued" className={button}>Mark issued internally</button>}
					<button name="to" value="cancelled" className={input}>Cancel record</button>
				</form>}
			</article>)}
		</section>
	</div>
}
