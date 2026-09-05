import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { campaignHeader, keywordPerformance } from "@/lib/queries-drilldown"
import { parseDays } from "@/lib/range"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function GET(
	request: Request,
	{ params }: { params: Promise<{ campaignId: string }> },
) {
	const url = new URL(request.url)
	const days = parseDays(url.searchParams.get("days") ?? undefined)
	const { campaignId } = await params
	const tenantId = await currentTenantId()
	const data = await withTenant(tenantId, async (client) => ({
		days,
		campaign: await campaignHeader(client, decodeURIComponent(campaignId), days),
		keywords: await keywordPerformance(client, decodeURIComponent(campaignId), days),
	}))
	return NextResponse.json(data)
}
