// Product availability is separate from tenant/marketplace authorization evidence.
// None of these integrations is implemented. A readiness row is not a feature flag.
const unavailable = [
	{
		capability: "rank_sov",
		status: "EXTERNAL_DATA_REQUIRED",
		required: ["APPROVED_RANK_SOV_SOURCE", "PROVENANCE_AND_FRESHNESS_CONTRACT"],
	},
	{
		capability: "sponsored_brands",
		status: "WAITING_FOR_API_APPROVAL",
		required: ["SPONSORED_BRANDS_PROFILE_ACCESS", "SPONSORED_BRANDS_REPORT_CONTRACT"],
	},
	{
		capability: "sponsored_display",
		status: "WAITING_FOR_API_APPROVAL",
		required: ["SPONSORED_DISPLAY_PROFILE_ACCESS", "SPONSORED_DISPLAY_REPORT_CONTRACT"],
	},
	{
		capability: "amazon_marketing_cloud",
		status: "WAITING_FOR_AMC",
		required: ["AUTHORIZED_AMC_INSTANCE", "AMC_PRIVACY_REVIEW"],
	},
	{
		capability: "amazon_dsp",
		status: "WAITING_FOR_API_APPROVAL",
		required: ["AMAZON_DSP_ENTERPRISE_APPROVAL", "AMAZON_DSP_CAPABILITY_REVIEW"],
	},
] as const

export function externalCapabilityAvailability() {
	// Keep the catalog private and return a new value for every snapshot.
	return unavailable.map(entry => ({
		capability: entry.capability,
		status: entry.status,
		required: [...entry.required],
		implemented: false as const,
	}))
}
