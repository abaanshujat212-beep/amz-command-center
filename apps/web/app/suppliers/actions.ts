"use server"
import { revalidatePath } from "next/cache"
import { withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { createProduct,createQuote,createSupplier,registerDocument } from "@/lib/suppliers"
function raw(form:FormData){return Object.fromEntries(form.entries())}
async function run(form:FormData,fn:typeof createSupplier|typeof createProduct|typeof createQuote|typeof registerDocument){const a=await currentContext();await withTenant(a.tenantId,c=>fn(c,a.tenantId,a.userId,a.role,raw(form)));revalidatePath("/suppliers")}
export async function addSupplier(form:FormData){return run(form,createSupplier)}
export async function addProduct(form:FormData){return run(form,createProduct)}
export async function addQuote(form:FormData){return run(form,createQuote)}
export async function addDocument(form:FormData){return run(form,registerDocument)}
