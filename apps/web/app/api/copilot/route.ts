import { NextResponse } from "next/server"
import { answerKnownQuestion } from "@/lib/copilot-execution"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export async function POST(request: Request) {
	await currentContext()
	const body = await request.json().catch(() => ({})) as { question?: unknown }
	const question = typeof body.question === "string" ? body.question.trim() : ""
	if (!question) return NextResponse.json({ error: "question is required" }, { status: 400 })
	return NextResponse.json(answerKnownQuestion(question))
}
