import { NextResponse } from "next/server"
import { AuthenticationRequired, TenantSelectionRequired } from "@/lib/session"
import { ReportRequestError } from "@/lib/reports"

export function reportError(err: unknown): NextResponse | null {
	if (err instanceof ReportRequestError) return NextResponse.json({ error: err.message }, { status: err.status })
	if (err instanceof AuthenticationRequired) return NextResponse.json({ error: err.message }, { status: 401 })
	if (err instanceof TenantSelectionRequired) return NextResponse.json({ error: err.message }, { status: 409 })
	return null
}
