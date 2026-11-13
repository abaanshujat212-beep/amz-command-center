import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
import { monthlyBudgetForecast, recentDryRunSummaries } from "@/lib/queries-budget-forecast"

export const dynamic = "force-dynamic"

export async function GET() {
	const actor = await currentContext()
	const result = await withTenant(actor.tenantId, async client => ({
		forecast: await monthlyBudgetForecast(client),
		simulations: await recentDryRunSummaries(client),
	}))
	return NextResponse.json(result)
}
