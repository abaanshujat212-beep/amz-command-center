import Link from "next/link"
import { notFound } from "next/navigation"
import { withTenant } from "@/lib/db"
import { stamp } from "@/lib/format"
import { getListingProjectPreview } from "@/lib/listings"
import { parseListingVersion } from "@/lib/listing-preview-input"
import { currentContext } from "@/lib/session"

export const dynamic = "force-dynamic"

function textList(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []
}

export default async function ListingPreview({ params, searchParams }: {
	params: Promise<{ id:string }>
	searchParams: Promise<{ version?:string | string[] }>
}) {
	const actor = await currentContext()
	const {id} = await params
	const {version: rawVersion} = await searchParams
	const version = parseListingVersion(rawVersion)
	if (rawVersion !== undefined && version === null) notFound()
	const data = await withTenant(actor.tenantId, c => getListingProjectPreview(c, actor.tenantId, id, version))
	if (!data) notFound()
	const { project, draft, validation, issues, versions, reviews } = data
	const projectPath = "/listings/" + encodeURIComponent(project.id)
	const bullets = textList(draft?.bullets)
	const terms = textList(draft?.backend_terms)
	return <div className="space-y-5">
		<header>
			<Link href="/listings" className="text-sm text-blue-700 hover:underline">Back to Listing Studio</Link>
			<h1 className="text-lg font-semibold">{project.name}</h1>
			<p className="text-sm text-slate-600">{project.marketplace}{project.asin ? " · ASIN "+project.asin : ""}{project.sku ? " · SKU "+project.sku : ""}</p>
			<p className="text-sm">Project editorial state: {project.review_state.replaceAll("_"," ")}</p>
		</header>
		<p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">Read-only. Validation and editorial approval recorded here do not publish to Amazon.</p>
		<section className="space-y-2 rounded-lg border bg-white p-4">
			<h2 className="font-semibold">Draft versions</h2>
			{versions.length ? <ul className="flex flex-wrap gap-2">
				{versions.map(v => <li key={v.id}><Link href={projectPath+"?version="+v.version}
					aria-current={draft?.id===v.id?"page":undefined} className="block rounded border px-3 py-2 text-sm hover:bg-slate-100">
					v{v.version} · {v.origin.replaceAll("_"," ")}{v.id===versions[0].id?" (latest)":""}
				</Link></li>)}
			</ul> : <p className="text-sm text-slate-600">No draft versions yet.</p>}
			{data.versionsLimited && <p className="text-sm text-slate-600">Showing the 50 latest versions.</p>}
		</section>
		{draft && <section className="space-y-3 break-words rounded-lg border bg-white p-4">
			<h2 className="font-semibold">Draft preview · v{draft.version}</h2>
			<p className="text-sm text-slate-600">{draft.origin.replaceAll("_"," ")} · {stamp(draft.created_at)} · {draft.change_summary}</p>
			<h3 className="font-medium">{draft.title || "No title"}</h3>
			{bullets.length > 0 && <ul className="list-disc space-y-1 pl-5 text-sm">{bullets.map((bullet,i)=><li key={i}>{bullet}</li>)}</ul>}
			<p className="whitespace-pre-wrap text-sm">{draft.description || "No description"}</p>
			{terms.length > 0 && <p className="text-sm"><strong>Backend terms:</strong> {terms.join(", ")}</p>}
		</section>}
		<section className="space-y-2 break-words rounded-lg border bg-white p-4">
			<h2 className="font-semibold">Latest validation{draft ? " · v"+draft.version : ""}</h2>
			{validation ? <>
				<p className="text-sm">{validation.passed ? "Passed recorded checks" : "Did not pass"} · {validation.validator_version} · {stamp(validation.created_at)}</p>
				<p className="text-sm text-slate-600">Product type: {validation.product_type || "Unknown"} · Definition {validation.ptd_contract_verified ? "verified in this run" : "not verified"} · Restrictions: {validation.restrictions_status}</p>
				{issues.length ? <ul className="space-y-2">{issues.map(i=><li key={i.id} className="rounded border p-2 text-sm">
					<strong>{i.severity} · {i.field || i.code}</strong><p>{i.message}</p>
				</li>)}</ul> : <p className="text-sm text-slate-600">No issues recorded for this run.</p>}
				{data.issuesLimited && <p className="text-sm text-slate-600">Showing up to 100 issues (errors first).</p>}
			</> : <p className="text-sm text-slate-600">No validation recorded for this draft.</p>}
		</section>
		<section className="space-y-2 break-words rounded-lg border bg-white p-4">
			<h2 className="font-semibold">Editorial review history</h2>
			{reviews.length ? <ol className="space-y-2 text-sm">{reviews.map(review=><li key={review.id} className="rounded border p-2">
				<Link href={projectPath+"?version="+review.version} className="font-medium text-blue-700 hover:underline">v{review.version}</Link>
				{" · "+review.decision.replaceAll("_"," ")+" · "+stamp(review.created_at)}
				{review.comment && <p className="mt-1 whitespace-pre-wrap text-slate-600">{review.comment}</p>}
			</li>)}</ol> : <p className="text-sm text-slate-600">No editorial decisions recorded.</p>}
			{data.reviewsLimited && <p className="text-sm text-slate-600">Showing the latest 50 decisions.</p>}
		</section>
	</div>
}
