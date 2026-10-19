"use server"
import { revalidatePath } from "next/cache"
import { createBudgetLimit } from "@/lib/budget-governance"
import { withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
export async function createLimit(form:FormData){const a=await currentContext();await withTenant(a.tenantId,c=>createBudgetLimit(c,a.tenantId,a.userId,a.role,Object.fromEntries(form.entries())));revalidatePath("/settings/portfolio-budgets")}
