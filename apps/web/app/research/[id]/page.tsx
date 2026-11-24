import Link from "next/link"
import { notFound } from "next/navigation"
import { withTenant } from "@/lib/db"
import { stamp } from "@/lib/format"
import { getResearchEvidence } from "@/lib/research"
import { presentResearchEvidence } from "@/lib/research-evidence"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

export default async function ResearchEvidencePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const actor = await currentContext()
  const result = await withTenant(actor.tenantId, c => getResearchEvidence(c, actor.tenantId, id))
  if (!result) notFound()
  const { candidate, observations, limited } = result
  const now = Date.now()
  return <div className="space-y-4">
    <header>
      <Link href="/research" className="text-sm text-blue-700 hover:underline">Back to product research</Link>
      <h1 className="text-lg font-semibold">{candidate.title}</h1>
      <p className="text-sm text-slate-600">{candidate.project_name} · {candidate.candidate_kind === "market" ? "Market research" : "Own catalog"}</p>
    </header>
    <p className="text-sm text-slate-600">These are recorded observations, not verified live estimates. Compare only like-for-like marketplace, period and grain. Partial, blocked and unverified values are not used as facts here.</p>
    {limited && <p className="text-sm text-slate-600">Showing the latest 100 observations.</p>}
    {observations.length === 0 ? <p className="rounded-lg border border-dashed bg-white p-5 text-sm">No evidence recorded. Market estimates are unavailable without an approved source.</p> :
      <ul className="space-y-2">
        {observations.map(row => {
          const evidence = presentResearchEvidence(row, now)
          return <li key={row.id} className="break-words rounded-lg border bg-white p-4 text-sm">
            <div className="flex flex-wrap justify-between gap-2"><h2 className="font-semibold">{row.metric}</h2><span>{evidence.quality}</span></div>
            <p className="mt-1 font-medium">{evidence.value === null ? "Value unavailable" : <>{evidence.value}{evidence.unit ? " "+evidence.unit : ""}</>}</p>
            <dl className="mt-2 grid gap-2 text-slate-600 sm:grid-cols-2">
              <div><dt className="font-medium">Provider</dt><dd>{evidence.provider || "Not recorded"}</dd></div>
              <div><dt className="font-medium">Observed</dt><dd>{evidence.observationTimeValid ? stamp(row.observed_at) : "Not verified"}</dd></div>
              <div><dt className="font-medium">Method</dt><dd>{evidence.method || "Not recorded"}</dd></div>
              <div><dt className="font-medium">Reference</dt><dd>{evidence.source || "Not recorded"}</dd></div>
            </dl>
            <div className="mt-2 text-slate-600">Source scope: {evidence.dimensions.length ? evidence.dimensions.map(({ key, value }) => key+": "+value).join(" · ") : "Not verified"}</div>
          </li>
        })}
      </ul>}
  </div>
}
