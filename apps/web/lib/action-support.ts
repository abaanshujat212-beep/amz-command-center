/** Live write paths with verified read/apply/rollback support in services/actions. */
const LIVE_SUPPORTED = new Set([
	"keyword:set_bid",
	"target:set_bid",
])

export function liveActionSupport(entityType: string, actionType: string): { supported: boolean; message: string } {
	if (LIVE_SUPPORTED.has(`${entityType}:${actionType}`)) {
		return { supported: true, message: "Live apply and rollback use the matching Ads entity endpoint." }
	}
	if (entityType === "campaign" && actionType === "set_placement_modifier") {
		return { supported: false, message: "Live apply exists, but rollback is not complete; approval is blocked." }
	}
	return { supported: false, message: "No verified live read/apply/rollback path; approval is blocked. Dry-run evaluation remains safe." }
}
