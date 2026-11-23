"use server"

import { redirect } from "next/navigation"
import { withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { approvePOSupplier, draftPO, transitionPO, PurchaseOrderError } from "@/lib/purchase-orders"

const path = "/suppliers/purchase-orders"
async function apply(form: FormData, operation: typeof draftPO | typeof transitionPO) {
	const a = await currentContext()
	try {
		await withTenant(a.tenantId, c => operation(c,a.tenantId,a.userId,a.role,form))
	} catch (e) {
		if (e instanceof PurchaseOrderError) redirect(path + "?error=" + encodeURIComponent(e.message))
		throw e
	}
	redirect(path)
}
export async function createPO(form: FormData) { return apply(form,draftPO) }
export async function changePO(form: FormData) { return apply(form,transitionPO) }
export async function approveSupplierForPO(form: FormData) { return apply(form,approvePOSupplier) }
