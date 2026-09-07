import type { TenantRole } from "@/lib/db"

export type AssignableRole = "admin" | "user" | "analyst" | "viewer"
export const ACCESS_SCOPES = ["reporting", "ads", "sp_api", "copilot", "approvals", "settings"] as const
export type AccessScope = typeof ACCESS_SCOPES[number]

export function defaultScopes(role: string): AccessScope[] {
	if (role === "admin") return ["reporting", "ads", "sp_api", "copilot", "approvals", "settings"]
	if (role === "user") return ["reporting", "ads", "sp_api", "copilot", "approvals"]
	if (role === "analyst") return ["reporting", "ads", "sp_api", "copilot"]
	return ["reporting"]
}

export function scopeLabel(scope: string): string {
	if (scope === "sp_api") return "SP-API / Seller data"
	return scope[0].toUpperCase() + scope.slice(1)
}

export function mayManageMembers(role: TenantRole): boolean { return role === "owner" || role === "admin" }
export function mayManageTenant(role: TenantRole): boolean { return role === "owner" || role === "admin" }
export function mayAssignRole(actor: TenantRole, target: AssignableRole): boolean { if (actor === "owner") return true; return actor === "admin" && (target === "user" || target === "analyst" || target === "viewer") }
export function roleDescription(role: string): string { if (role === "owner") return "Full tenant control"; if (role === "admin") return "Team, settings and approvals"; if (role === "user") return "Operator dashboard and approvals"; if (role === "analyst") return "Analysis and reporting access"; if (role === "viewer") return "Read-only dashboard access"; return "Custom limited access" }
