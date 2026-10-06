import type { PoolClient, QueryResultRow } from "pg"
import { query, type TenantRole } from "@/lib/db"

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const EDIT = new Set<TenantRole>(["owner", "admin", "user", "analyst"])
const MANAGE = new Set<TenantRole>(["owner", "admin"])
const KINDS = new Set(["own_catalog", "market"])
const STATES = new Set(["new", "watchlist", "shortlisted", "rejected"])

export class ResearchInputError extends Error {
	constructor(message: string, readonly status = 400) { super(message) }
}

export type ResearchCandidateView = QueryResultRow & {
	id: string; project_id: string; project_name: string; candidate_kind: "own_catalog" | "market"
	title: string; asin: string | null; sku: string | null; status: string
	observation_count: number; complete_count: number; partial_count: number; blocked_count: number
	latest_observed_at: string | null
}

function text(value: unknown, name: string, limit: number) {
	if (typeof value !== "string" || !value.trim() || value.trim().length > limit) throw new ResearchInputError(`${name} is required`)
	return value.trim()
}

export async function listResearchCandidates(client: PoolClient, tenantId: string) {
	return query<ResearchCandidateView>(client, `select c.id,c.project_id,p.name as project_name,c.candidate_kind,c.title,c.asin,c.sku,c.status,
		count(o.id)::int as observation_count,
		count(o.id) filter(where o.completeness='complete')::int as complete_count,
		count(o.id) filter(where o.completeness='partial')::int as partial_count,
		count(o.id) filter(where o.completeness='blocked')::int as blocked_count,
		max(o.observed_at)::text as latest_observed_at
	from research_candidate c join research_project p on p.id=c.project_id and p.tenant_id=c.tenant_id
	left join research_observation o on o.candidate_id=c.id and o.tenant_id=c.tenant_id
	where c.tenant_id=$1 group by c.id,p.name order by c.updated_at desc`, [tenantId])
}

export async function createResearchProject(client: PoolClient, tenantId: string, userId: string, role: TenantRole, raw: Record<string, unknown>) {
	if (!EDIT.has(role)) throw new ResearchInputError("your role cannot create research projects", 403)
	const rows = await query<{ id: string }>(client, `insert into research_project(tenant_id,name,objective,created_by)
		values($1,$2,$3,$4) returning id`, [tenantId, text(raw.name, "name", 200), typeof raw.objective === "string" ? raw.objective.trim() || null : null, userId])
	return rows[0]
}

export async function createResearchCandidate(client: PoolClient, tenantId: string, userId: string, role: TenantRole, raw: Record<string, unknown>) {
	if (!EDIT.has(role)) throw new ResearchInputError("your role cannot create research candidates", 403)
	if (typeof raw.projectId !== "string" || !UUID.test(raw.projectId)) throw new ResearchInputError("valid projectId is required")
	if (typeof raw.candidateKind !== "string" || !KINDS.has(raw.candidateKind)) throw new ResearchInputError("candidateKind must be own_catalog or market")
	const asin = typeof raw.asin === "string" ? raw.asin.trim() || null : null
	const sku = typeof raw.sku === "string" ? raw.sku.trim() || null : null
	if (raw.candidateKind === "own_catalog" && !asin && !sku) throw new ResearchInputError("own-catalog candidates require an ASIN or SKU")
	const rows = await query<{ id: string }>(client, `insert into research_candidate(tenant_id,project_id,candidate_kind,asin,sku,title,created_by)
		values($1,$2,$3,$4,$5,$6,$7) returning id`, [tenantId, raw.projectId, raw.candidateKind, asin, sku, text(raw.title, "title", 300), userId])
	return rows[0]
}

export async function setResearchDisposition(client: PoolClient, tenantId: string, role: TenantRole, id: string, status: unknown) {
	if (!MANAGE.has(role)) throw new ResearchInputError("only owners or admins can change shortlist state", 403)
	if (!UUID.test(id)) throw new ResearchInputError("invalid candidate id")
	if (typeof status !== "string" || !STATES.has(status)) throw new ResearchInputError("invalid candidate status")
	const rows = await query<{ id: string }>(client, "update research_candidate set status=$1,updated_at=now() where tenant_id=$2 and id=$3 returning id", [status, tenantId, id])
	if (!rows[0]) throw new ResearchInputError("candidate not found", 404)
	return rows[0]
}
