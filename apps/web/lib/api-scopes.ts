export const API_SCOPES = ["read", "approve", "write", "settings:read", "settings:write"] as const
export type ApiScope = typeof API_SCOPES[number]

export function scopeDescription(scope: string): string {
	if (scope === "settings:read") return "Read company display name and reporting timezone through the settings API."
	if (scope === "settings:write") return "Edit company display name and reporting timezone. Does not enable Amazon actions or change safety controls."
	if (scope === "read") return "Read tenant KPIs, history, opportunities and approvals."
	if (scope === "approve") return "Approve/reject queued proposals through guarded approval contracts."
	if (scope === "write") return "Sensitive future write tools. Disabled by default; requires explicit warning and audited routes."
	return "Unknown scope."
}

export function isSensitiveScope(scope: string): boolean {
	return scope === "approve" || scope === "write" || scope === "settings:write"
}

export function allowedApiScopes(requested: string[]): ApiScope[] {
	const allowed = new Set<string>(API_SCOPES)
	const scopes = requested.filter((scope): scope is ApiScope => allowed.has(scope))
	return scopes.length ? Array.from(new Set(scopes)) : ["read"]
}
