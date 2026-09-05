import type { TenantRole } from "@/lib/db"

export type AssignableRole = "admin" | "user"

export function mayManageMembers(role: TenantRole): boolean {
	return role === "owner" || role === "admin"
}

export function mayManageTenant(role: TenantRole): boolean {
	return role === "owner" || role === "admin"
}

export function mayAssignRole(actor: TenantRole, target: AssignableRole): boolean {
	return actor === "owner" || (actor === "admin" && target === "user")
}
