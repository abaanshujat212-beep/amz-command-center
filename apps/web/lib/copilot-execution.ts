import { COPILOT_QUESTIONS } from "./copilot-benchmarks"

export type CopilotResult = { ok: boolean; question: string; tier: "T1" | "T2"; answer: string; sql?: string; notes: string[]; requiresConfirmation: boolean; source: "text" | "voice"; runnerMode: "contract" | "external" }

const WRITE_PATTERN = /(apply|approve|change|set|increase|decrease|pause|enable|lagao|chalao|recommend|suggest|proposal|kya karna|kia karna|bid|budget|negative|harvest)/i
const REQUIRED_CONTRACT = ["tenant_id", "question", "tier", "source", "no_write", "requires_confirmation"] as const

export function classifyCopilotPrompt(question: string, source: "text" | "voice" = "text") {
	const text = question.trim()
	const known = COPILOT_QUESTIONS.find(q => q.question === text || q.questionUr === text || q.key === text)
	const tier = known?.tier ?? (WRITE_PATTERN.test(text) ? "T2" : "T1")
	return { text, known, tier, requiresConfirmation: tier === "T2" || (source === "voice" && WRITE_PATTERN.test(text)) }
}

export function buildRunnerPayload(question: string, tenantId: string, source: "text" | "voice" = "text") {
	const c = classifyCopilotPrompt(question, source)
	return { tenant_id: tenantId, question: c.text, tier: c.tier, source, no_write: true, requires_confirmation: c.requiresConfirmation, benchmark_key: c.known?.key ?? null }
}

export function assertRunnerContract(payload: Record<string, unknown>) {
	for (const key of REQUIRED_CONTRACT) if (!(key in payload)) throw new Error(`copilot runner payload missing ${key}`)
	if (payload.no_write !== true) throw new Error("copilot runner payload must be no_write=true")
	if (payload.tier === "T2" && payload.requires_confirmation !== true) throw new Error("T2 copilot prompts must require confirmation")
}

export function answerKnownQuestion(question: string, source: "text" | "voice" = "text", tenantId = "unknown"): CopilotResult {
	const payload = buildRunnerPayload(question, tenantId, source)
	assertRunnerContract(payload)
	const c = classifyCopilotPrompt(question, source)
	if (c.tier === "T2") return { ok: true, question: c.text, tier: c.tier, source, requiresConfirmation: c.requiresConfirmation, runnerMode: "contract", answer: "This is a proposal-only request. The copilot boundary built a valid no-write runner payload, but it will not write to Amazon or create an action directly. Route the recommendation through the rules/approval queue before any numeric change executes.", notes: ["runner contract validated", "confirm-before-execute required", "no auto-apply path", source === "voice" ? "voice input treated as higher risk" : "text input"] }
	return { ok: true, question: c.text, tier: c.tier, source, requiresConfirmation: c.requiresConfirmation, runnerMode: "contract", answer: c.known ? `Runner contract ready for audited read-only execution: ${c.known.intent}.` : "Runner contract ready for tenant-scoped read-only copilot execution once the Python service process is deployed beside Next.js.", notes: ["tenant-scoped", "read-only", "audited", "row-capped", "runner payload validated", source === "voice" ? "captured from voice transcript" : "text input"] }
}
