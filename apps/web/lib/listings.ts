import type { PoolClient, QueryResultRow } from "pg"
import { query, type TenantRole } from "@/lib/db"
import { validateListingDraft } from "@/lib/listing-validation"

const EDIT = new Set<TenantRole>(["owner", "admin", "user", "analyst"])
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export class ListingInputError extends Error { constructor(message: string, readonly status = 400) { super(message) } }
export type ListingProjectView = QueryResultRow & { id:string; name:string; asin:string|null; sku:string|null; marketplace:string; review_state:string; version:number|null; draft_title:string|null; origin:string|null; created_at:string|null; review_count:number; validation_passed:boolean|null; validation_issue_count:number }

function required(value: unknown, name: string, max: number) {
	if (typeof value !== "string" || !value.trim() || value.trim().length > max) throw new ListingInputError(`${name} is required`)
	return value.trim()
}

export async function listListingProjects(client: PoolClient, tenantId: string) {
	return query<ListingProjectView>(client, `select p.id,p.name,p.asin,p.sku,p.marketplace,p.review_state,
		d.version,d.title as draft_title,d.origin,d.created_at::text,v.passed as validation_passed,coalesce(v.issue_count,0)::int as validation_issue_count,
		(select count(*)::int from listing_review_event e where e.tenant_id=p.tenant_id and e.project_id=p.id) as review_count
	from listing_project p left join lateral(select * from listing_draft_version v where v.tenant_id=p.tenant_id and v.project_id=p.id order by v.version desc limit 1)d on true
	left join lateral(select r.passed,(select count(*) from listing_validation_issue i where i.tenant_id=r.tenant_id and i.validation_run_id=r.id) as issue_count from listing_validation_run r where r.tenant_id=p.tenant_id and r.draft_version_id=d.id order by r.created_at desc limit 1)v on true
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
	const keywordPlanVersionId = typeof raw.keywordPlanVersionId === "string" && UUID.test(raw.keywordPlanVersionId) ? raw.keywordPlanVersionId : null
	const rows = await query<{id:string;version:number}>(client,`insert into listing_draft_version(tenant_id,project_id,version,previous_version_id,title,bullets,description,backend_terms,keyword_plan_version_id,origin,generation_ref,change_summary,created_by)
		values($1,$2,$3,$4,$5,$6::jsonb,$7,$8::jsonb,$9,$10,$11,$12,$13) returning id,version`,[tenantId,projectId,version,prior[0]?.id??null,typeof raw.title === "string" ? raw.title : "",JSON.stringify(bullets),typeof raw.description === "string" ? raw.description : "",JSON.stringify(terms),keywordPlanVersionId,origin,generationRef,required(raw.changeSummary,"changeSummary",1000),userId])
	for (const factId of new Set(facts)) await query(client,"insert into listing_draft_fact(tenant_id,draft_version_id,product_fact_id) values($1,$2,$3)",[tenantId,rows[0].id,factId])
	await query(client,"update listing_project set review_state='draft',updated_at=now() where tenant_id=$1 and id=$2",[tenantId,projectId])
	return rows[0]
}

type DraftValidationRow = { id:string; title:string; bullets:string[]; description:string; backend_terms:string[]; keyword_plan_version_id:string|null }
type FactRow = { id:string; fact_key:string; value:unknown; source_type:string; source_ref:string }

export async function validateLatestListingDraft(client:PoolClient,tenantId:string,userId:string,role:TenantRole,projectId:string) {
	if (!EDIT.has(role)) throw new ListingInputError("your role cannot validate listing drafts",403)
	if (!UUID.test(projectId)) throw new ListingInputError("invalid project id")
	const drafts=await query<DraftValidationRow>(client,"select id,title,bullets,description,backend_terms,keyword_plan_version_id from listing_draft_version where tenant_id=$1 and project_id=$2 order by version desc limit 1",[tenantId,projectId])
	const draft=drafts[0]; if(!draft) throw new ListingInputError("listing draft not found",404)
	const facts=await query<FactRow>(client,`select f.id,f.fact_key,f.value,f.source_type,f.source_ref from listing_product_fact f join listing_draft_fact df on df.tenant_id=f.tenant_id and df.product_fact_id=f.id where f.tenant_id=$1 and df.draft_version_id=$2`,[tenantId,draft.id])
	const plans=draft.keyword_plan_version_id ? await query<{keywords:string[]}>(client,"select keywords from listing_keyword_plan_version where tenant_id=$1 and id=$2",[tenantId,draft.keyword_plan_version_id]) : []
	const verified=(key:string)=>facts.find(f=>f.fact_key===key && ["catalog","provider"].includes(f.source_type) && f.source_ref.startsWith("amazon:"))
	const productType=verified("product_type")?.value
	const restrictions=verified("restrictions_status")?.value
	const result=validateListingDraft({title:draft.title,bullets:draft.bullets,description:draft.description,backendTerms:draft.backend_terms,citedFactIds:facts.map(f=>f.id),availableFactIds:facts.map(f=>f.id),keywordBank:plans[0]?.keywords??[],productType:typeof productType==="string"?productType:null,ptdContractVerified:typeof productType==="string",restrictionsStatus:typeof restrictions==="string"?restrictions:"unknown"})
	const runs=await query<{id:string}>(client,`insert into listing_validation_run(tenant_id,project_id,draft_version_id,validator_version,product_type,ptd_contract_verified,restrictions_status,passed,validated_by) values($1,$2,$3,'listing-v1',$4,$5,$6,$7,$8) returning id`,[tenantId,projectId,draft.id,typeof productType==="string"?productType:null,typeof productType==="string",typeof restrictions==="string"&&["unknown","clear","restricted","blocked","error"].includes(restrictions)?restrictions:"unknown",result.passed,userId])
	for(const issue of result.issues) await query(client,"insert into listing_validation_issue(tenant_id,validation_run_id,code,field,severity,message) values($1,$2,$3,$4,$5,$6)",[tenantId,runs[0].id,issue.code,issue.field,issue.severity,issue.message])
	return {runId:runs[0].id,...result}
}

export async function reviewListingDraft(client:PoolClient,tenantId:string,userId:string,role:TenantRole,projectId:string,raw:Record<string,unknown>) {
	if (!UUID.test(projectId) || typeof raw.draftVersionId !== "string" || !UUID.test(raw.draftVersionId)) throw new ListingInputError("valid project and draft ids are required")
	const targets:Record<string,string>={submitted:"in_review",approved:"approved",changes_requested:"changes_requested",returned_to_draft:"draft"}
	if (typeof raw.decision !== "string" || !targets[raw.decision]) throw new ListingInputError("invalid review decision")
	if (raw.decision !== "submitted" && !new Set<TenantRole>(["owner","admin"]).has(role)) throw new ListingInputError("only owners or admins may decide reviews",403)
	if (raw.decision === "submitted" && !EDIT.has(role)) throw new ListingInputError("your role cannot submit drafts",403)
	const latest=await query<{id:string}>(client,"select id from listing_draft_version where tenant_id=$1 and project_id=$2 order by version desc limit 1 for update",[tenantId,projectId])
	if (latest[0]?.id !== raw.draftVersionId) throw new ListingInputError("only the latest draft can enter review",409)
	if (["submitted","approved"].includes(raw.decision)) {
		const validation=await query<{passed:boolean}>(client,"select passed from listing_validation_run where tenant_id=$1 and draft_version_id=$2 order by created_at desc limit 1",[tenantId,raw.draftVersionId])
		if (validation[0]?.passed !== true) throw new ListingInputError("draft must pass the latest deterministic validation before review",409)
	}
	await query(client,"insert into listing_review_event(tenant_id,project_id,draft_version_id,decision,comment,actor_user_id) values($1,$2,$3,$4,$5,$6)",[tenantId,projectId,raw.draftVersionId,raw.decision,typeof raw.comment === "string" ? raw.comment : null,userId])
	await query(client,"update listing_project set review_state=$1,updated_at=now() where tenant_id=$2 and id=$3",[targets[raw.decision],tenantId,projectId])
}
