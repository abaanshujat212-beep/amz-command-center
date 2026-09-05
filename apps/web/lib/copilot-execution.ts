import { COPILOT_QUESTIONS } from "./copilot-benchmarks"

export type CopilotResult = { ok: boolean; question: string; tier: "T1" | "T2"; answer: string; sql?: string; notes: string[] }

export function answerKnownQuestion(question: string): CopilotResult {
	const text = question.trim()
	const known = COPILOT_QUESTIONS.find(q => q.question === text || q.questionUr === text || q.key === text)
	const tier = known?.tier ?? (/(apply|approve|change|set|increase|decrease|pause|enable|lagao|chalao|recommend|suggest|proposal|kya karna|kia karna)/i.test(text) ? "T2" : "T1")
	if (tier === "T2") return { ok: true, question: text, tier, answer: "This is a proposal-only request. The copilot API boundary accepted the prompt, but it will not write to Amazon or create an action directly. Route the recommendation through the rules/approval queue before any numeric change executes.", notes: ["confirm-before-execute required", "no auto-apply path"] }
	return { ok: true, question: text, tier, answer: known ? `Ready to execute through the audited read-only copilot runner: ${known.intent}.` : "Ready to execute as a tenant-scoped read-only copilot question once DATABASE_URL_COPILOT is configured in this deployment.", notes: ["tenant-scoped", "read-only", "audited", "row-capped"] }
}
