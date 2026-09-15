import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { reportError } from "@/lib/report-api"
import { authorizedArtifact, readAuthorizedArtifact } from "@/lib/reports"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"
type Params = { params: Promise<{ id: string }> }

export async function GET(_request: Request, { params }: Params) {
	try {
		const actor = await currentContext()
		const { id } = await params
		const artifact = await withTenant(actor.tenantId, c => authorizedArtifact(c, actor.tenantId, id))
		const bytes = await readAuthorizedArtifact(artifact)
		return new NextResponse(bytes, { headers: {
			"Cache-Control": "private, no-store",
			"Content-Disposition": `attachment; filename="report-${id}.${artifact.file_extension}"`,
			"Content-Length": String(bytes.byteLength),
			"Content-Type": artifact.media_type,
		} })
	} catch (err) { const response = reportError(err); if (response) return response; throw err }
}
