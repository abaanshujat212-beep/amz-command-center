import type { PoolClient, QueryResultRow } from "pg"
import { query, type TenantRole } from "@/lib/db"

const EDIT = new Set<TenantRole>(["owner", "admin", "user", "analyst"])
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export class ListingInputError extends Error { constructor(message: string, readonly status = 400) { super(message) } }
export type ListingProjectView = QueryResultRow & { id:string; name:string; asin:string|null; sku:string|null; marketplace:string; review_state:string; version:number|null; draft_title:string|null; origin:string|null; created_at:string|null; review_count:number }

function required(value: unknown, name: string, max: number) {
	if (typeof value !== "string" || !value.trim() || value.trim().length > max) throw new ListingInputError(`${name} is required`)
	return value.trim()
}

export async function listListingProjects(client: PoolClient, tenantId: string) {
	return query<ListingProjectView>(client, `select p.id,p.name,p.asin,p.sku,p.marketplace,p.review_state,
		d.version,d.title as draft_title,d.origin,d.created_at::text,
		(select count(*)::int from listing_review_event e where e.tenant_id=p.tenant_id and e.project_id=p.id) as review_count
	from listing_project p left join lateral(select * from listing_draft_version v where v.tenant_id=p.tenant_id and v.project_id=p.id order by v.version desc limit 1)d on true
	where p.tenant_id=$1 order by p.updated_at desc`, [tenantId])
}

export async function createListingProject(client: PoolClient, tenantId: string, userId: string, role: TenantRole, raw: Record<string, unknown>) {
	if (!EDIT.has(role)) throw new ListingInputError("your role cannot create listing projects", 403)
	const researchCandidateId = typeof raw.researchCandidateId === "string" && UUID.test(raw.researchCandidateId) ? raw.researchCandidateId : null
	const rows = await query<{id:string}>(client, `insert into listing_project(tenant_id,research_candidate_id,name,asin,sku,created_by)
		values($1,$2,$3,$4,$5,$6) returning id`, [tenantId, researchCandidateId, required(raw.name,"name",200), typeof raw.asin === "string" ? raw.asin.trim() || null : null, typeof raw.sku === "string" ? raw.sku.trim() || null : null, userId])
	return rows[0]
}

export async function createListingDraft(client: PoolClient, tenantId: string, userId: string, role: TenantRole, projectId: string, raw: Record<string, unknown>) {
	if (!EDIT.has(role)) throw new ListingInputError("your role cannot create listing drafts",403)
	if (!UUID.test(projectId)) throw new ListingInputError("invalid project id")
	const bullets = Array.isArray(raw.bullets) && raw.bullets.every(v => typeof v === "string") ? raw.bullets : []
	const terms = Array.isArray(raw.backendTerms) && raw.backendTerms.every(v => typeof v === "string") ? raw.backendTerms : []
	if (bullets.length > 10 || bullets.some(v => v.length > 1000)) throw new ListingInputError("listing content exceeds safe limits")
	const origin = typeof raw.origin === "string" ? raw.origin : "human"
	if (!["human","ai_assisted","imported"].includes(origin)) throw new ListingInputError("invalid draft origin")
	const generationRef = typeof raw.generationRef === "string" ? raw.generationRef.trim() || null : null
	if (origin === "ai_assisted" && !generationRef) throw new ListingInputError("AI-assisted drafts require generation provenance")
	const project = await query<{review_state:string}>(client,"select review_state from listing_project where tenant_id=$1 and id=$2 for update",[tenantId,projectId])
	if (!project[0]) throw new ListingInputError("listing project not found",404)
	if (project[0].review_state === "archived") throw new ListingInputError("archived projects cannot be edited",409)
	const prior = await query<{id:string;version:number}>(client,"select id,version from listing_draft_version where tenant_id=$1 and project_id=$2 order by version desc limit 1",[tenantId,projectId])
	const version = (prior[0]?.version ?? 0) + 1
	const facts = Array.isArray(raw.productFactIds) && raw.productFactIds.every(v => typeof v === "string" && UUID.test(v)) ? raw.productFactIds : []
	const rows = await query<{id:string;version:number}>(client,`insert into listing_draft_version(tenant_id,project_id,version,previous_version_id,title,bullets,description,backend_terms,origin,generation_ref,change_summary,created_by)
		values($1,$2,$3,$4,$5,$6::jsonb,$7,$8::jsonb,$9,$10,$11,$12) returning id,version`,[tenantId,projectId,version,prior[0]?.id??null,typeof raw.title === "string" ? raw.title : "",JSON.stringify(bullets),typeof raw.description === "string" ? raw.description : "",JSON.stringify(terms),origin,generationRef,required(raw.changeSummary,"changeSummary",1000),userId])
	for (const factId of new Set(facts)) await query(client,"insert into listing_draft_fact(tenant_id,draft_version_id,product_fact_id) values($1,$2,$3)",[tenantId,rows[0].id,factId])
	await query(client,"update listing_project set review_state='draft',updated_at=now() where tenant_id=$1 and id=$2",[tenantId,projectId])
	return rows[0]
}

export async function reviewListingDraft(client:PoolClient,tenantId:string,userId:string,role:TenantRole,projectId:string,raw:Record<string,unknown>) {
	if (!UUID.test(projectId) || typeof raw.draftVersionId !== "string" || !UUID.test(raw.draftVersionId)) throw new ListingInputError("valid project and draft ids are required")
	const targets:Record<string,string>={submitted:"in_review",approved:"approved",changes_requested:"changes_requested",returned_to_draft:"draft"}
	if (typeof raw.decision !== "string" || !targets[raw.decision]) throw new ListingInputError("invalid review decision")
	if (raw.decision !== "submitted" && !new Set<TenantRole>(["owner","admin"]).has(role)) throw new ListingInputError("only owners or admins may decide reviews",403)
	if (raw.decision === "submitted" && !EDIT.has(role)) throw new ListingInputError("your role cannot submit drafts",403)
	const latest=await query<{id:string}>(client,"select id from listing_draft_version where tenant_id=$1 and project_id=$2 order by version desc limit 1 for update",[tenantId,projectId])
	if (latest[0]?.id !== raw.draftVersionId) throw new ListingInputError("only the latest draft can enter review",409)
	await query(client,"insert into listing_review_event(tenant_id,project_id,draft_version_id,decision,comment,actor_user_id) values($1,$2,$3,$4,$5,$6)",[tenantId,projectId,raw.draftVersionId,raw.decision,typeof raw.comment === "string" ? raw.comment : null,userId])
	await query(client,"update listing_project set review_state=$1,updated_at=now() where tenant_id=$2 and id=$3",[targets[raw.decision],tenantId,projectId])
}
