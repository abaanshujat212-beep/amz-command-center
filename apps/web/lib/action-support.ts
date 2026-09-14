import registry from "../../../packages/shared/action_capabilities.json"

type Capability = {
	recommendation_supported: boolean
	approval_supported: boolean
	live_baseline_read_supported: boolean
	live_apply_supported: boolean
	rollback_supported: boolean
	verification_supported: boolean
	local_only: boolean
}

const EMPTY: Capability = {
	recommendation_supported: false,
	approval_supported: false,
	live_baseline_read_supported: false,
	live_apply_supported: false,
	rollback_supported: false,
	verification_supported: false,
	local_only: false,
}

export function actionCapability(entityType: string, actionType: string): Capability {
	const entries = registry as Record<string, Capability>
	return entries[`${entityType}:${actionType}`] ?? entries[`*:${actionType}`] ?? EMPTY
}

export function liveActionSupport(entityType: string, actionType: string, readinessState?: string, verificationLevel?: string): { supported: boolean; message: string; capability: Capability } {
	const capability = actionCapability(entityType, actionType)
	const authorizedEvidence = verificationLevel === "AUTHORIZED_LIVE_READ" || verificationLevel === "AUTHORIZED_LIVE_WRITE"
	const complete = capability.recommendation_supported && capability.approval_supported && capability.live_baseline_read_supported && capability.live_apply_supported && capability.rollback_supported && capability.verification_supported && !capability.local_only
	if (complete && readinessState === "LIVE_READY" && authorizedEvidence) {
		return { supported: true, message: "Capability is live-ready with authorized evidence.", capability }
	}
	return { supported: false, message: "Capability is recommend-only, unsupported, or lacks authorized LIVE_READY evidence; approval is blocked.", capability }
}
