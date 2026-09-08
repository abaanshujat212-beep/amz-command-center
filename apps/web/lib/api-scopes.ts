export const API_SCOPES = ["read", "approve", "write"] as const
export type ApiScope = typeof API_SCOPES[number]

export function scopeDescription(scope: string): string {
	if (scope === "read") return "Read tenant KPIs, history, opportunities and approvals."
	if (scope === "approve") return "Approve/reject queued proposals through guarded approval contracts."
	if (scope === "write") return "Sensitive future write tools. Disabled by default; requires explicit warning and audited routes."
	return "Unknown scope."
}

export function isSensitiveScope(scope: string): boolean {
	return scope === "approve" || scope === "write"
}

export function allowedApiScopes(requested: string[]): ApiScope[] {
	const allowed = new Set<string>(API_SCOPES)
	const scopes = requested.filter((scope): scope is ApiScope => allowed.has(scope))
	return scopes.length ? Array.from(new Set(scopes)) : ["read"]
}
