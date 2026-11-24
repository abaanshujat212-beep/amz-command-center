import { notFound } from "next/navigation"
import { withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { receiptHistory } from "@/lib/receipt-history"

export const dynamic = "force-dynamic"

export default async function ReceiptHistoryPage({params}:{params:Promise<{id:string}>}) {
  const context = await currentContext()
  const {id} = await params
  const data = await withTenant(context.tenantId, c=>receiptHistory(c,context.tenantId,id))
  if (!data) notFound()
  const {order,receipts} = data
  return <div className="space-y-6">
    <header className="space-y-2">
      <a href="/suppliers/purchase-orders" className="text-sm underline">Back to purchase orders</a>
      <h1 className="text-lg font-semibold">Receiving review history</h1>
      <p className="text-sm text-slate-600">{order.supplier_name} · {order.product_name} · {order.product_sku} · {order.state}</p>
      <p className="text-sm text-slate-600">Reviewed delivery evidence only. These quantities have not been posted to inventory or cost accounts. Recording deliveries from this screen is not yet available.</p>
    </header>
    <dl className="grid gap-4 sm:grid-cols-4">
      {[["Ordered",order.quantity],["Accepted in reviews",order.accepted],["Damaged in reviews",order.damaged],["Unreviewed quantity",order.outstanding]].map(([label,value])=><div key={label} className="rounded border bg-white p-4"><dt className="text-sm text-slate-600">{label}</dt><dd className="mt-2 text-lg font-semibold">{value}</dd></div>)}
    </dl>
    <section className="space-y-3">
      <h2 className="font-medium">{order.review_count} receipt reviews</h2>
      {order.review_count>100&&<p className="text-sm text-slate-600">Showing the latest 100 reviews. Totals include all reviews.</p>}
      {!receipts.length?<p className="rounded border p-4 text-sm text-slate-600">No receipt evidence recorded for this order.</p>:<div className="overflow-x-auto rounded border bg-white"><table className="w-full text-left text-sm">
        <thead className="bg-slate-50"><tr>{["Observed (UTC)","Location / market","Sellable SKU","Reference","Accepted","Damaged"].map(label=><th key={label} className="p-3 font-medium">{label}</th>)}</tr></thead>
        <tbody>{receipts.map(r=><tr key={r.id} className="border-t"><td className="p-3">{new Date(r.observed_at).toISOString()}</td><td className="p-3">{r.location_name} · {r.marketplace_id}</td><td className="p-3">{r.sellable_sku}</td><td className="p-3">{r.source_ref}</td><td className="p-3">{r.accepted}</td><td className="p-3">{r.damaged}</td></tr>)}</tbody>
      </table></div>}
    </section>
  </div>
}
