import { NextResponse } from "next/server"
import { answerKnownQuestion, buildRunnerPayload } from "@/lib/copilot-execution"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function POST(request: Request) {
	const actor = await currentContext()
	const body = await request.json().catch(() => ({})) as { question?: unknown; source?: unknown; includeRunnerPayload?: unknown }
	const question = typeof body.question === "string" ? body.question.trim() : ""
	const source = body.source === "voice" ? "voice" : "text"
	if (!question) return NextResponse.json({ error: "question is required" }, { status: 400 })
	const result = answerKnownQuestion(question, source, actor.tenantId)
	if (body.includeRunnerPayload === true) return NextResponse.json({ ...result, runnerPayload: buildRunnerPayload(question, actor.tenantId, source) })
	return NextResponse.json(result)
}
