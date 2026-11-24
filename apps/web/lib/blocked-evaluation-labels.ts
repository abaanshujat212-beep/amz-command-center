const REASONS: Readonly<Record<string, {title: string; nextStep: string}>> = {
	NATIVE_OPTIMIZATION_CONFLICT: {title: "Amazon-native control conflict", nextStep: "Keep Amazon in control, or request a separate, explicitly approved transfer to AXATY."},
	NATIVE_CONTROL_EVIDENCE_MISSING: {title: "Amazon control settings unknown", nextStep: "Refresh and verify the campaign’s Amazon-native control settings."},
	NATIVE_CONTROL_EVIDENCE_INVALID: {title: "Amazon control evidence invalid", nextStep: "Refresh the snapshot and check the source clock."},
	NATIVE_CONTROL_EVIDENCE_STALE: {title: "Amazon control evidence out of date", nextStep: "Refresh the native-control snapshot before proposing a change."},
	NATIVE_CONTROL_UNSUPPORTED: {title: "Amazon bidding strategy unsupported", nextStep: "Keep Amazon in control until its current strategy can be verified."},
	kill_switch: {title: "Automation switched off", nextStep: "Review the workspace’s automation settings with its owner."},
	dry_run: {title: "Dry-run mode", nextStep: "Review the result without sending a change to Amazon."},
	stale_data: {title: "Data out of date", nextStep: "Refresh the source data before evaluating again."},
	unsettled_data: {title: "Performance data still settling", nextStep: "Wait for the reporting window to settle."},
	thin_data: {title: "Not enough performance data", nextStep: "Wait for more qualifying impressions or clicks."},
	cooldown: {title: "Recent change still in cooldown", nextStep: "Wait before evaluating another change."},
	daily_change_limit: {title: "Daily change limit reached", nextStep: "Review the next eligible run."},
	daily_budget_limit: {title: "Daily budget increase limit reached", nextStep: "Review the next eligible run."},
	blast_radius: {title: "Too many entities would change", nextStep: "Review the rule’s scope before evaluating again."},
	bounds: {title: "Proposed value outside allowed bounds", nextStep: "Review the rule and its bid or budget limits."},
	economics_incomplete: {title: "Costs or break-even data unavailable", nextStep: "Complete the cost data before evaluating profitability."},
	protected_entity: {title: "Entity protected", nextStep: "Leave the protection in place unless an authorized operator removes it."},
	human_control: {title: "Entity under human control", nextStep: "Ask the assigned operator whether automation should resume."},
	duplicate_target: {title: "Duplicate target or pending proposal", nextStep: "Review the existing target or proposal."},
	harvest_route_missing: {title: "No eligible harvest destination", nextStep: "Review the approved destination rules."},
	harvest_route_conflict: {title: "Harvest destinations conflict", nextStep: "Resolve conflicting destination rules before running again."},
	unsupported_action: {title: "Action not supported", nextStep: "Review supported actions before proposing a change."},
}

export function blockedEvaluationReason(raw: unknown) {
	if (typeof raw === "string" && Object.hasOwn(REASONS, raw)) {
		return {code: raw, ...REASONS[raw]}
	}
	return {code: null, title: "Other guardrail block", nextStep: "Review the optimizer diagnostics for this run."}
}

const TYPES: Readonly<Record<string, string>> = {
	bid_adjustment: "Bid adjustment", budget_adjustment: "Budget adjustment",
	entity_state: "Entity status change", negative_targeting: "Negative targeting",
	keyword_harvest: "Keyword harvest", placement_adjustment: "Placement adjustment", diagnostic: "Diagnostic",
}

export function blockedEvaluationType(raw: unknown) {
	return typeof raw === "string" && Object.hasOwn(TYPES, raw) ? TYPES[raw] : null
}
