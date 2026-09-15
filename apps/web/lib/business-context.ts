import { authPool } from "@/lib/auth"
import { query, withTenant } from "@/lib/db"

export type BusinessContext = {
	workspaceId: string | null
	brandId: string | null
	channelAccountId: string | null
	marketplaceContextId: string | null
	adsProfileId: string | null
}

export function safeReturnRoute(value: unknown): string {
	return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") ? value : "/"
}

export async function assertWorkspaceOperation(token: string, workspaceId: string, tenantId: string) {
	const { rows } = await authPool.query(
		"select * from public.session_workspace_tenant_authorization($1,$2,$3)",
		[token, workspaceId, tenantId],
	)
	if (rows.length !== 1) throw new Error("workspace tenant operation is not authorized")
	return rows[0]
}

export async function assertBusinessHierarchy(tenantId: string, context: BusinessContext) {
	if (!context.brandId && (context.channelAccountId || context.marketplaceContextId || context.adsProfileId)) throw new Error("brand context is required")
	if (!context.channelAccountId && (context.marketplaceContextId || context.adsProfileId)) throw new Error("channel account context is required")
	if (!context.marketplaceContextId && context.adsProfileId) throw new Error("marketplace context is required")
	if (!context.brandId) return
	await withTenant(tenantId, async client => {
		const rows = await query<{ valid: boolean }>(client, `select
			exists(select 1 from brand where tenant_id=$1 and id=$2) and
			($3::uuid is null or exists(select 1 from channel_account where tenant_id=$1 and id=$3 and brand_id=$2)) and
			($4::uuid is null or exists(select 1 from marketplace_context where tenant_id=$1 and id=$4 and channel_account_id=$3)) and
			($5::uuid is null or exists(select 1 from advertising_profile_context where tenant_id=$1 and marketplace_context_id=$4 and ads_profile_id=$5)) as valid`,
			[tenantId, context.brandId, context.channelAccountId, context.marketplaceContextId, context.adsProfileId])
		if (rows[0]?.valid !== true) throw new Error("business context is not valid for this tenant")
	})
}
