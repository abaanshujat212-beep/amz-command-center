import Link from "next/link"
import { BLOCKED_EVALUATION_LIMIT, listBlockedEvaluations } from "@/lib/blocked-evaluations"
import { withTenant } from "@/lib/db"
import { currentTenantId } from "@/lib/session"

export const dynamic = "force-dynamic"

export default async function BlockedRecommendations() {
	const tenantId = await currentTenantId()
	const evaluations = await withTenant(tenantId, client => listBlockedEvaluations(client, tenantId))
	return <div className="space-y-5">
		<Link href="/recommendations" className="text-sm text-slate-600">← Recommendation Center</Link>
		<header>
			<h1 className="text-lg font-semibold">Blocked evaluations</h1>
			<p className="mt-1 text-sm text-slate-600">The latest {BLOCKED_EVALUATION_LIMIT} rule matches stopped by a guardrail. These are not queued for approval and cannot be applied here.</p>
		</header>
		{evaluations.length ? <ul className="space-y-3">{evaluations.map(item =>
			<li key={item.id} className="rounded-lg border border-slate-200 bg-white p-4">
				<h2 className="font-medium">{item.reason.title}</h2>
				<p className="mt-1 text-sm text-slate-700">{item.reason.nextStep}</p>
				<p className="mt-2 text-xs text-slate-600">
					{item.type && <>{item.type} · </>}Evaluated {item.evaluatedAt} · Data through {item.dataThrough}
					{item.reason.code && <> · <code>{item.reason.code}</code></>}
				</p>
			</li>)}</ul> : <p className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
			No blocked rule matches have been recorded for this workspace.
		</p>}
	</div>
}
