import { ReportRequestForm } from "@/components/report-request-form"
import { ReportRetryButton } from "@/components/report-retry-button"
import { withTenant } from "@/lib/db"
import { mayRequestReports, listReports, type ReportView } from "@/lib/reports"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

function tone(status: string) { if (status === "succeeded") return "tone-good"; if (status === "failed") return "tone-bad"; if (status === "running") return "tone-warn"; return "text-slate-500" }
function stamp(value: string | null) { return value ? new Date(value).toLocaleString("en-GB") : "—" }
function Artifact({ report }: { report: ReportView }) {
	if (report.artifact_state === "AVAILABLE") return <a href={`/api/reports/${report.id}/download`} className="text-blue-700 hover:underline">Download {report.output_format.toUpperCase()}</a>
	if (report.artifact_state === "EXPIRED") return <span className="text-amber-700">Expired</span>
	if (report.artifact_state === "UNAVAILABLE") return <span className="text-slate-500">Artifact unavailable</span>
	return <span className="text-slate-400">Not ready</span>
}

export default async function ReportsPage() {
	const actor = await currentContext()
	const reports = await withTenant(actor.tenantId, c => listReports(c, actor.tenantId))
	const canRequest = mayRequestReports(actor.role)
	const today = new Date(); const from = new Date(today); from.setUTCDate(from.getUTCDate() - 30)
	return <div className="space-y-5">
		<div><h1 className="text-lg font-semibold">Reports</h1><p className="text-sm text-slate-600">Governed, reproducible exports. Long-running work remains visible here.</p></div>
		{canRequest ? <ReportRequestForm dateFrom={from.toISOString().slice(0, 10)} dateTo={today.toISOString().slice(0, 10)} /> : <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">Read-only: your role can view and download reports but cannot create or retry them.</div>}
		{reports.length === 0 ? <div className="rounded-lg border bg-white p-8 text-sm text-slate-600">No reports yet. A queued report is not marked available until rendering, hashing and artifact reconciliation succeed.</div> : <ul className="space-y-3">{reports.map(report => <li key={report.id} className="rounded-lg border border-slate-200 bg-white p-4">
			<div className="flex flex-wrap items-start justify-between gap-3"><div><div className="font-medium">Account summary · {report.output_format.toUpperCase()}</div><div className="text-xs text-slate-500">{report.date_from} → {report.date_to} · definition v{report.definition_version} · attempt {report.attempt}/{report.max_attempts}</div></div><span className={`text-sm font-medium ${tone(report.status)}`}>{report.status}</span></div>
			<div className="mt-3 flex flex-wrap items-center gap-3 text-sm"><Artifact report={report} />{report.status === "failed" && canRequest && report.attempt < report.max_attempts && <ReportRetryButton id={report.id} />}<a href={`/api/reports/${report.id}`} className="text-slate-500 hover:underline">Status JSON</a></div>
			{report.error && <p className="mt-2 text-sm text-red-700">{report.error}</p>}
			<details className="mt-3 text-xs text-slate-600"><summary className="cursor-pointer">Scope and reconciliation</summary><div className="mt-2 grid gap-1 sm:grid-cols-2"><span>Queued: {stamp(report.queued_at)}</span><span>Finished: {stamp(report.finished_at)}</span><span>Rows: {report.row_count ?? "unknown"}</span><span>Bytes: {report.byte_size ?? "unknown"}</span><span>Expires: {stamp(report.expires_at)}</span><span>Hash: {report.content_sha256 ?? "not available"}</span></div><pre className="mt-2 overflow-x-auto rounded bg-slate-50 p-2">{JSON.stringify({ filters: report.filters, reconciliation: report.reconciliation }, null, 2)}</pre></details>
		</li>)}</ul>}
		<p className="text-xs text-slate-500">Scheduled and external delivery are not enabled. Downloads are re-authorized and integrity-checked on every request.</p>
	</div>
}
