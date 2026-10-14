import type { PoolClient, QueryResultRow } from "pg"
import { query, type TenantRole } from "@/lib/db"

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const EDIT = new Set<TenantRole>(["owner", "admin", "user", "analyst"])
export const DASHBOARD_WIDGET_TYPES = ["scorecard", "table", "timeseries", "bar"] as const
export const DASHBOARD_QUERIES = ["dashboard.summary", "campaign.performance", "search_terms.performance", "product.economics", "sqp.opportunities", "pipeline.health"] as const
export const DASHBOARD_FILTER_FIELDS = ["marketplace", "dateRange", "campaignId", "asin", "sku", "status"] as const
export const DASHBOARD_FILTER_OPERATORS = ["eq", "in", "between", "gte", "lte"] as const

export type DashboardFilter = { field: string; operator: string; value: unknown }
export type DashboardWidget = { id: string; type: string; query: string; title?: string; layout: { x: number; y: number; w: number; h: number }; filters?: DashboardFilter[]; [key: string]: unknown }
type Filter = DashboardFilter
type Widget = DashboardWidget
export type DashboardDefinition = { schemaVersion: 1; widgets: Widget[]; globalFilters?: Filter[]; [key: string]: unknown }
export type DashboardRow = QueryResultRow & { id: string; name: string; visibility: "private" | "team"; owner_user_id: string; source_template_key: string | null; source_template_version: number | null; current_version: number; definition: DashboardDefinition; is_default?: boolean; template_update_available?: boolean; updated_at?: string }
export type DashboardTemplateRow = QueryResultRow & { template_key: string; name: string; description: string | null; current_version: number; definition: DashboardDefinition; release_notes: string }

export class DashboardInputError extends Error {
	constructor(message: string, readonly status = 400) { super(message) }
}

function requiredText(value: unknown, label: string, limit = 120) {
	if (typeof value !== "string" || !value.trim() || value.trim().length > limit) throw new DashboardInputError(`${label} is required and must be at most ${limit} characters`)
	return value.trim()
}
function object(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value) }
function allowed(value: string, values: readonly string[]) { return values.includes(value) }
function validateFilter(value: unknown): asserts value is Filter {
	if (!object(value) || typeof value.field !== "string" || !allowed(value.field, DASHBOARD_FILTER_FIELDS) || typeof value.operator !== "string" || !allowed(value.operator, DASHBOARD_FILTER_OPERATORS) || !("value" in value)) throw new DashboardInputError("dashboard filter is not allowlisted")
}
export function parseDashboardDefinition(value: unknown): DashboardDefinition {
	if (!object(value) || value.schemaVersion !== 1 || !Array.isArray(value.widgets) || value.widgets.length > 50) throw new DashboardInputError("definition must use schemaVersion 1 and contain at most 50 widgets")
	const ids = new Set<string>()
	for (const candidate of value.widgets) {
		if (!object(candidate) || typeof candidate.id !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(candidate.id) || ids.has(candidate.id)) throw new DashboardInputError("widget IDs must be unique safe identifiers")
		ids.add(candidate.id)
		if (typeof candidate.type !== "string" || !allowed(candidate.type, DASHBOARD_WIDGET_TYPES)) throw new DashboardInputError("widget type is not allowlisted")
		if (typeof candidate.query !== "string" || !allowed(candidate.query, DASHBOARD_QUERIES)) throw new DashboardInputError("widget query is not allowlisted")
		const layout = candidate.layout
		if (!object(layout) || !["x", "y", "w", "h"].every(key => Number.isInteger(layout[key])) || Number(layout.w) < 1 || Number(layout.w) > 12 || Number(layout.h) < 1 || Number(layout.h) > 20) throw new DashboardInputError("widget layout is invalid")
		if (candidate.filters !== undefined) { if (!Array.isArray(candidate.filters)) throw new DashboardInputError("widget filters must be an array"); candidate.filters.forEach(validateFilter) }
	}
	if (value.globalFilters !== undefined) { if (!Array.isArray(value.globalFilters)) throw new DashboardInputError("globalFilters must be an array"); value.globalFilters.forEach(validateFilter) }
	return value as DashboardDefinition
}

async function visibleDashboard(client: PoolClient, id: string) {
	if (!UUID.test(id)) throw new DashboardInputError("invalid dashboard id")
	const rows = await query<DashboardRow>(client, `select d.*,v.definition from dashboard d join dashboard_version v on v.tenant_id=d.tenant_id and v.dashboard_id=d.id and v.version=d.current_version where d.id=$1 and not d.is_archived`, [id])
	if (!rows[0]) throw new DashboardInputError("dashboard not found", 404)
	return rows[0]
}
function canChange(row: DashboardRow, userId: string, role: TenantRole) { if (row.owner_user_id !== userId && role !== "owner" && role !== "admin") throw new DashboardInputError("only the dashboard owner or a tenant administrator can change it", 403) }
async function audit(client: PoolClient, tenantId: string, userId: string, action: string, entity: string, after: unknown) { await query(client, "insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,$3,$4,$5::jsonb)", [tenantId,userId,action,entity,JSON.stringify(after)]) }

export async function listDashboards(client: PoolClient, userId: string) {
	return query(client, `select d.id,d.name,d.visibility,d.owner_user_id,d.source_template_key,d.source_template_version,d.current_version,d.updated_at,df.user_id is not null as is_default,v.definition,(t.current_version is not null and t.current_version>d.source_template_version) as template_update_available from dashboard d join dashboard_version v on v.tenant_id=d.tenant_id and v.dashboard_id=d.id and v.version=d.current_version left join dashboard_default df on df.tenant_id=d.tenant_id and df.dashboard_id=d.id and df.user_id=$1 left join dashboard_template t on t.template_key=d.source_template_key where not d.is_archived order by is_default desc,d.updated_at desc`, [userId])
}
export async function listDashboardTemplates(client: PoolClient) {
	return query<DashboardTemplateRow>(client, `select t.template_key,t.name,t.description,t.current_version,v.definition,v.release_notes from dashboard_template t join dashboard_template_version v on v.template_key=t.template_key and v.version=t.current_version order by t.name`)
}
export async function createDashboard(client: PoolClient, tenantId: string, userId: string, role: TenantRole, raw: Record<string, unknown>) {
	if (!EDIT.has(role)) throw new DashboardInputError("your role cannot create dashboards", 403)
	const name = requiredText(raw.name,"name"), visibility = raw.visibility === "team" ? "team" : raw.visibility === "private" ? "private" : null
	if (!visibility) throw new DashboardInputError("visibility must be private or team")
	let definition: DashboardDefinition, templateKey: string | null = null, templateVersion: number | null = null
	if (typeof raw.templateKey === "string") {
		const version = Number.isInteger(raw.templateVersion) ? Number(raw.templateVersion) : null
		const templates = await query<{template_key:string;version:number;definition:DashboardDefinition}>(client, `select v.template_key,v.version,v.definition from dashboard_template_version v join dashboard_template t on t.template_key=v.template_key where v.template_key=$1 and v.version=coalesce($2,t.current_version)`, [raw.templateKey,version])
		if (!templates[0]) throw new DashboardInputError("dashboard template version not found",404)
		definition=parseDashboardDefinition(templates[0].definition); templateKey=templates[0].template_key; templateVersion=templates[0].version
	} else definition=parseDashboardDefinition(raw.definition)
	const rows=await query<{id:string}>(client,`insert into dashboard(tenant_id,name,visibility,owner_user_id,source_template_key,source_template_version) values($1,$2,$3,$4,$5,$6) returning id`,[tenantId,name,visibility,userId,templateKey,templateVersion])
	await query(client,`insert into dashboard_version(tenant_id,dashboard_id,version,definition,change_summary,created_by) values($1,$2,1,$3::jsonb,'Initial dashboard',$4)`,[tenantId,rows[0].id,JSON.stringify(definition),userId])
	await audit(client,tenantId,userId,"dashboard.created",`dashboard:${rows[0].id}`,{name,visibility,templateKey,templateVersion})
	return visibleDashboard(client,rows[0].id)
}
export async function updateDashboard(client: PoolClient, tenantId: string, userId: string, role: TenantRole, id: string, raw: Record<string, unknown>) {
	if (!EDIT.has(role)) throw new DashboardInputError("your role cannot edit dashboards",403)
	const row=await visibleDashboard(client,id); canChange(row,userId,role)
	const name=raw.name===undefined?null:requiredText(raw.name,"name"), visibility=raw.visibility===undefined?null:raw.visibility
	if (visibility!==null && visibility!=="private" && visibility!=="team") throw new DashboardInputError("visibility must be private or team")
	let nextVersion=row.current_version
	if (raw.definition!==undefined) { const definition=parseDashboardDefinition(raw.definition); nextVersion++;
		await query(client,`insert into dashboard_version(tenant_id,dashboard_id,version,definition,change_summary,created_by) values($1,$2,$3,$4::jsonb,$5,$6)`,[tenantId,id,nextVersion,JSON.stringify(definition),requiredText(raw.changeSummary,"changeSummary",300),userId]) }
	await query(client,`update dashboard set name=coalesce($1,name),visibility=coalesce($2,visibility),current_version=$3,updated_at=now() where id=$4`,[name,visibility,nextVersion,id])
	await audit(client,tenantId,userId,"dashboard.updated",`dashboard:${id}`,{version:nextVersion,name,visibility})
	return visibleDashboard(client,id)
}
export async function archiveDashboard(client: PoolClient, tenantId: string, userId: string, role: TenantRole, id: string) { const row=await visibleDashboard(client,id); canChange(row,userId,role); await query(client,"update dashboard set is_archived=true,updated_at=now() where id=$1",[id]); await audit(client,tenantId,userId,"dashboard.archived",`dashboard:${id}`,{}); return {id} }
export async function duplicateDashboard(client: PoolClient, tenantId: string, userId: string, role: TenantRole, id: string, raw: Record<string,unknown>) { const source=await visibleDashboard(client,id); return createDashboard(client,tenantId,userId,role,{name:raw.name??`${source.name} copy`,visibility:raw.visibility??"private",definition:source.definition}) }
export async function setDefaultDashboard(client: PoolClient, tenantId: string, userId: string, id: string) { await visibleDashboard(client,id); await query(client,`insert into dashboard_default(tenant_id,user_id,dashboard_id) values($1,$2,$3) on conflict(tenant_id,user_id) do update set dashboard_id=excluded.dashboard_id,created_at=now()`,[tenantId,userId,id]); await audit(client,tenantId,userId,"dashboard.default_set",`dashboard:${id}`,{}); return {id} }
export async function clearDefaultDashboard(client: PoolClient, tenantId: string, userId: string, id: string) { await query(client,"delete from dashboard_default where tenant_id=$1 and user_id=$2 and dashboard_id=$3",[tenantId,userId,id]); await audit(client,tenantId,userId,"dashboard.default_cleared",`dashboard:${id}`,{}); return {id} }

/** Explicit upgrade pins the new AXATY version while preserving the complete user definition. */
export async function upgradeDashboardTemplate(client: PoolClient, tenantId: string, userId: string, role: TenantRole, id: string) {
	const row=await visibleDashboard(client,id); canChange(row,userId,role)
	if (!row.source_template_key) throw new DashboardInputError("dashboard is not based on an AXATY template")
	const templates=await query<{current_version:number}>(client,"select current_version from dashboard_template where template_key=$1",[row.source_template_key])
	if (!templates[0] || templates[0].current_version<=Number(row.source_template_version)) throw new DashboardInputError("dashboard already uses the latest template",409)
	// The user's version remains untouched; future canvas work may offer an opt-in structural merge.
	await query(client,"update dashboard set source_template_version=$1,updated_at=now() where id=$2",[templates[0].current_version,id])
	await audit(client,tenantId,userId,"dashboard.template_upgraded",`dashboard:${id}`,{from:row.source_template_version,to:templates[0].current_version,userVersion:row.current_version})
	return visibleDashboard(client,id)
}
