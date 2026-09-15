export type ModuleVisibility = "DISABLED" | "RECOMMENDED" | "ENABLED" | "BETA" | "EXTERNAL_ACCESS_REQUIRED" | "NOT_READY"
export type ModuleNavigationState = { module_key: string; visibility_state: ModuleVisibility; reason_code: string | null }
export type DomainLink = { href: string; label: string; moduleKey?: string }
export type DomainGroup = { label: string; links: readonly DomainLink[] }

export const DOMAIN_GROUPS: readonly DomainGroup[] = [
	{ label: "Home", links: [{ href: "/", label: "Command Center" }] },
	{ label: "Products", links: [{ href: "/opportunities", label: "Opportunities" }, { href: "/sqp", label: "SQP opportunities" }] },
	{ label: "Decisions", links: [{ href: "/approvals", label: "Approvals" }, { href: "/verification", label: "Verification" }, { href: "/history", label: "History" }] },
	{ label: "Ads / PPC", links: [{ href: "/campaigns", label: "Campaigns" }, { href: "/search-terms", label: "Search terms" }, { href: "/placements", label: "Placements" }] },
	{ label: "Finance", links: [{ href: "/economics", label: "Economics" }] },
	{ label: "AI", links: [{ href: "/copilot", label: "Copilot" }] },
]

export function navigationState(link: DomainLink, states: readonly ModuleNavigationState[]) {
	if (!link.moduleKey) return { visible: true, enabled: true, reason: null }
	const state = states.find(item => item.module_key === link.moduleKey)
	if (!state || state.visibility_state === "DISABLED") return { visible: false, enabled: false, reason: state?.reason_code ?? null }
	const enabled = state.visibility_state === "ENABLED" || state.visibility_state === "BETA" || state.visibility_state === "RECOMMENDED"
	return { visible: true, enabled, reason: state.reason_code ?? state.visibility_state.replaceAll("_", " ").toLowerCase() }
}
