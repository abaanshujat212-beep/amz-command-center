import type { PoolClient } from "pg"
import { query, type TenantRole } from "@/lib/db"

const operators = new Set<TenantRole>(["owner", "admin", "user"])
const managers = new Set<TenantRole>(["owner", "admin"])
export const canDraftPO = (role: TenantRole) => operators.has(role)
export const canManagePO = (role: TenantRole) => managers.has(role)

export class PurchaseOrderError extends Error {}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function orderId(value: FormDataEntryValue | null): string {
	if (typeof value !== "string" || !uuid.test(value)) throw new PurchaseOrderError("Invalid order or quote.")
	return value
}

async function audit(c: PoolClient, tenant: string, user: string, id: string, action: string, before: string | null, after: string) {
	await query(c, `insert into audit_log(tenant_id,actor_user_id,action,entity,before,after)
		values($1,$2,$3,$4,$5::jsonb,$6::jsonb)`,
	[tenant,user,`supplier.purchase_order.${action}`,`supplier_purchase_order:${id}`,before && JSON.stringify({ state: before }),JSON.stringify({ state: after })])
}

export async function draftPO(c: PoolClient, tenant: string, actor: string, role: TenantRole, form: FormData) {
	if (!canDraftPO(role)) throw new PurchaseOrderError("Your role cannot create purchase orders.")
	const id = orderId(form.get("id")), quoteId = orderId(form.get("quote"))
	const quantity = form.get("quantity")
	if (typeof quantity !== "string" || !/^\d{1,8}(\.\d{1,4})?$/.test(quantity) || Number(quantity) <= 0) {
		throw new PurchaseOrderError("Enter a positive quantity with up to four decimal places.")
	}
	const inserted = await query<{id:string}>(c, `insert into supplier_purchase_order
		(id,tenant_id,quote_id,supplier_name,product_sku,product_name,quote_ref,quote_version,currency,unit_price,quantity,created_by)
		select $1,q.tenant_id,q.id,p.display_name,sp.sku,sp.product_name,q.quote_ref,q.version,q.currency,q.unit_price,$4::numeric,$5
		from supplier_quote q
		join supplier_profile s on s.tenant_id=q.tenant_id and s.party_id=q.supplier_party_id
		join supplier_product sp on sp.id=q.supplier_product_id and sp.tenant_id=q.tenant_id and sp.supplier_party_id=q.supplier_party_id
		join party p on p.id=q.supplier_party_id and p.tenant_id=q.tenant_id
		where q.tenant_id=$2 and q.id=$3 and q.superseded_at is null and q.quoted_on <= current_date
		and (q.valid_until is null or q.valid_until >= current_date) and sp.active
		and s.status in ('prospect','approved') and $4::numeric >= coalesce(q.moq,sp.moq,0)
		on conflict(id) do nothing returning id`, [id,tenant,quoteId,quantity,actor])
	if (inserted[0]) {
		await audit(c,tenant,actor,id,"drafted",null,"draft")
		return
	}
	const existing = await query<{id:string}>(c,`select id from supplier_purchase_order
		where id=$1 and tenant_id=$2 and quote_id=$3 and quantity=$4::numeric and created_by=$5`, [id,tenant,quoteId,quantity,actor])
	if (!existing[0]) throw new PurchaseOrderError("Could not draft the order. Check the current quote, supplier and minimum quantity.")
}

export async function transitionPO(c: PoolClient, tenant: string, actor: string, role: TenantRole, form: FormData) {
	if (!canManagePO(role)) throw new PurchaseOrderError("Only owners and admins can issue or cancel orders.")
	const id = orderId(form.get("id")), from = form.get("from"), to = form.get("to")
	if (!((from === "draft" && (to === "issued" || to === "cancelled")) || (from === "issued" && to === "cancelled"))) {
		throw new PurchaseOrderError("Invalid purchase order transition.")
	}
	const changed = await query<{id:string}>(c,`update supplier_purchase_order o set state=$4,updated_at=now()
		where o.tenant_id=$1 and o.id=$2 and o.state=$3 and ($4 <> 'issued' or exists (
			select 1 from supplier_quote q
			join supplier_profile s on s.tenant_id=q.tenant_id and s.party_id=q.supplier_party_id
			join supplier_product p on p.tenant_id=q.tenant_id and p.id=q.supplier_product_id
			where q.tenant_id=o.tenant_id and q.id=o.quote_id and q.superseded_at is null
			and (q.valid_until is null or q.valid_until >= current_date) and p.active and s.status='approved'
		)) returning id`, [tenant,id,from,to])
	if (!changed[0]) throw new PurchaseOrderError("Order is unavailable or already changed. Issuing requires an approved supplier and a current quote.")
	await audit(c,tenant,actor,id,to,from,to)
}

export async function approvePOSupplier(c: PoolClient, tenant: string, actor: string, role: TenantRole, form: FormData) {
	if (!canManagePO(role)) throw new PurchaseOrderError("Only owners and admins can approve suppliers.")
	const id = orderId(form.get("supplier"))
	const rows = await query<{party_id:string}>(c,`update supplier_profile set status='approved',updated_at=now()
		where tenant_id=$1 and party_id=$2 and status='prospect' returning party_id`,[tenant,id])
	if (!rows[0]) throw new PurchaseOrderError("Supplier is unavailable or no longer a prospect.")
	await query(c,`insert into audit_log(tenant_id,actor_user_id,action,entity,before,after)
		values($1,$2,'supplier.approved',$3,'{"status":"prospect"}'::jsonb,'{"status":"approved"}'::jsonb)`,[tenant,actor,`supplier:${id}`])
}
