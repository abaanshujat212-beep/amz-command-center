import type { TenantRole } from "@/lib/db"

export type AssignableRole = "admin" | "user" | "analyst" | "viewer"

export function mayManageMembers(role: TenantRole): boolean {
	return role === "owner" || role === "admin"
}

export function mayManageTenant(role: TenantRole): boolean {
	return role === "owner" || role === "admin"
}

export function mayAssignRole(actor: TenantRole, target: AssignableRole): boolean {
	if (actor === "owner") return true
	return actor === "admin" && (target === "user" || target === "analyst" || target === "viewer")
}

export function roleDescription(role: string): string {
	if (role === "owner") return "Full tenant control"
	if (role === "admin") return "Team, settings and approvals"
	if (role === "user") return "Operator dashboard and approvals"
	if (role === "analyst") return "Analysis and reporting access"
	if (role === "viewer") return "Read-only dashboard access"
	return "Limited access"
}
