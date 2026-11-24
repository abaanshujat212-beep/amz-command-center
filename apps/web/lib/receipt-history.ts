import { query } from "@/lib/db"
import type { PoolClient } from "pg"

export const RECEIPT_SUMMARY_SQL = `
  select o.id,o.product_sku,o.product_name,o.supplier_name,o.state,o.quantity::text,
    (coalesce(sum((r.evidence->>'accepted_units')::numeric),0)/10000)::text accepted,
    (coalesce(sum((r.evidence->>'damaged_units')::numeric),0)/10000)::text damaged,
    (o.quantity-coalesce(sum((r.evidence->>'accepted_units')::numeric+
      (r.evidence->>'damaged_units')::numeric),0)/10000)::text outstanding,
    count(r.id)::int review_count
  from supplier_purchase_order o
  left join purchase_receipt_review r on r.tenant_id=o.tenant_id and r.order_id=o.id
  where o.tenant_id=$1 and o.id=$2
  group by o.id`

export const RECEIPT_HISTORY_SQL = `
  select r.id,r.observed_at::text,r.created_at::text,r.source_ref,
    r.evidence->>'sellable_sku' sellable_sku,
    r.evidence->>'marketplace_id' marketplace_id,
    ((r.evidence->>'accepted_units')::numeric/10000)::text accepted,
    ((r.evidence->>'damaged_units')::numeric/10000)::text damaged,
    l.display_name location_name
  from purchase_receipt_review r
  join inventory_location l on l.tenant_id=r.tenant_id and l.id=r.location_id
  where r.tenant_id=$1 and r.order_id=$2
  order by r.observed_at desc,r.id limit 100`

type Summary = {id:string;product_sku:string;product_name:string;supplier_name:string;state:string;quantity:string;accepted:string;damaged:string;outstanding:string;review_count:number}
type Receipt = {id:string;observed_at:string;created_at:string;source_ref:string;sellable_sku:string;marketplace_id:string;accepted:string;damaged:string;location_name:string}

export async function receiptHistory(client: PoolClient, tenantId: string, orderId: string) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(orderId)) return null
  const [order] = await query<Summary>(client, RECEIPT_SUMMARY_SQL, [tenantId,orderId])
  if (!order) return null
  return {order,receipts:await query<Receipt>(client, RECEIPT_HISTORY_SQL, [tenantId,orderId])}
}
