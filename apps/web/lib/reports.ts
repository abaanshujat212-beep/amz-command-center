import { createHash } from "node:crypto"
import { readFile } from "node:fs/promises"
import { resolve, sep } from "node:path"
import type { PoolClient, QueryResultRow } from "pg"
import { query, type TenantRole } from "@/lib/db"

const DATE = /^\d{4}-\d{2}-\d{2}$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const FORMATS = new Set(["csv", "xlsx", "pdf"])
const REQUEST_ROLES = new Set<TenantRole>(["owner", "admin", "user", "analyst"])

export class ReportRequestError extends Error {
	constructor(message: string, readonly status = 400) { super(message) }
}

export type ReportView = QueryResultRow & {
	id: string
	definition_code: string
	definition_version: number
	date_from: string
	date_to: string
	filters: Record<string, unknown>
	output_format: "csv" | "xlsx" | "pdf"
	status: "queued" | "running" | "succeeded" | "failed" | "canceled"
	attempt: number
	max_attempts: number
	queued_at: string
	started_at: string | null
	finished_at: string | null
	error: string | null
	artifact_state: "PENDING" | "AVAILABLE" | "EXPIRED" | "UNAVAILABLE" | "FAILED"
	content_sha256: string | null
	byte_size: number | null
	row_count: number | null
	reconciliation: Record<string, unknown> | null
	expires_at: string | null
}

type ArtifactDownload = QueryResultRow & {
	storage_key: string
	content_sha256: string
	media_type: string
	file_extension: string
	byte_size: number
}

export type CreateReportInput = {
	dateFrom: unknown
	dateTo: unknown
	filters: unknown
	outputFormat: unknown
	idempotencyKey: unknown
}

export function mayRequestReports(role: TenantRole): boolean {
	return REQUEST_ROLES.has(role)
}

function validDate(value: unknown, name: string): string {
	if (typeof value !== "string" || !DATE.test(value)) throw new ReportRequestError(`${name} must be YYYY-MM-DD`)
	const parsed = new Date(`${value}T00:00:00Z`)
	if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) throw new ReportRequestError(`${name} is invalid`)
	return value
}

function validateInput(input: CreateReportInput) {
	const dateFrom = validDate(input.dateFrom, "dateFrom")
	const dateTo = validDate(input.dateTo, "dateTo")
	if (dateFrom > dateTo) throw new ReportRequestError("dateFrom must not be after dateTo")
	const span = (Date.parse(`${dateTo}T00:00:00Z`) - Date.parse(`${dateFrom}T00:00:00Z`)) / 86_400_000
	if (span > 366) throw new ReportRequestError("report range cannot exceed 366 days")
	if (typeof input.outputFormat !== "string" || !FORMATS.has(input.outputFormat)) throw new ReportRequestError("outputFormat must be csv, xlsx or pdf")
	if (typeof input.idempotencyKey !== "string" || !input.idempotencyKey.trim() || input.idempotencyKey.length > 128) throw new ReportRequestError("a valid idempotencyKey is required")
	if (typeof input.filters !== "object" || input.filters === null || Array.isArray(input.filters)) throw new ReportRequestError("filters must be an object")
	if (JSON.stringify(input.filters).length > 4096) throw new ReportRequestError("filters are too large")
	return { dateFrom, dateTo, outputFormat: input.outputFormat, idempotencyKey: input.idempotencyKey, filters: input.filters as Record<string, unknown> }
}

async function ensureAccountDefinition(client: PoolClient, tenantId: string) {
	await query(client, `insert into report_definition(tenant_id,code,version,title,source_contract,render_contract_version,definition)
		values($1,'account-summary',1,'Account summary','governed-account-summary-v1',1,$2::jsonb)
		on conflict(tenant_id,code,version) do nothing`, [tenantId, JSON.stringify({ columns: ["date", "sales", "spend", "orders", "acos"] })])
}

const REPORT_SELECT = `select j.id,j.definition_code,j.definition_version,j.date_from::text,j.date_to::text,
	j.filters,j.output_format,j.status,j.attempt,j.max_attempts,j.queued_at::text,
	j.started_at::text,j.finished_at::text,j.error,a.content_sha256,a.byte_size,a.row_count,
	a.reconciliation,a.expires_at::text,
	case when j.status='failed' then 'FAILED'
		when j.status<>'succeeded' then 'PENDING'
		when a.id is null then 'UNAVAILABLE'
		when a.expires_at<=now() then 'EXPIRED'
		else 'AVAILABLE' end as artifact_state
	from report_job j left join report_artifact a
		on a.tenant_id=j.tenant_id and a.report_job_id=j.id`

function storageAware(report: ReportView): ReportView {
	if (report.artifact_state === "AVAILABLE" && !process.env.REPORT_ARTIFACT_ROOT) {
		return { ...report, artifact_state: "UNAVAILABLE" }
	}
	return report
}

export async function listReports(client: PoolClient, tenantId: string, limit = 100): Promise<ReportView[]> {
	const rows = await query<ReportView>(client, `${REPORT_SELECT} where j.tenant_id=$1 order by j.created_at desc limit $2`, [tenantId, Math.min(200, Math.max(1, limit))])
	return rows.map(storageAware)
}

export async function getReport(client: PoolClient, tenantId: string, jobId: string): Promise<ReportView> {
	if (!UUID.test(jobId)) throw new ReportRequestError("invalid report id")
	const rows = await query<ReportView>(client, `${REPORT_SELECT} where j.tenant_id=$1 and j.id=$2`, [tenantId, jobId])
	if (!rows[0]) throw new ReportRequestError("report not found", 404)
	return storageAware(rows[0])
}

export async function createReport(client: PoolClient, tenantId: string, userId: string, role: TenantRole, raw: CreateReportInput): Promise<ReportView> {
	if (!mayRequestReports(role)) throw new ReportRequestError("your tenant role cannot request reports", 403)
	const input = validateInput(raw)
	await ensureAccountDefinition(client, tenantId)
	const inserted = await query<{ id: string }>(client, `insert into report_job(
		tenant_id,report_definition_id,definition_code,definition_version,definition_snapshot,
		requested_by,idempotency_key,date_from,date_to,filters,output_format)
	select d.tenant_id,d.id,d.code,d.version,jsonb_build_object(
		'code',d.code,'version',d.version,'title',d.title,'source_contract',d.source_contract,
		'render_contract_version',d.render_contract_version,'definition',d.definition),
		$2,$3,$4,$5,$6::jsonb,$7
	from report_definition d where d.tenant_id=$1 and d.code='account-summary' and d.version=1 and d.active=true
	on conflict(tenant_id,idempotency_key) do nothing returning id`, [tenantId, userId, input.idempotencyKey, input.dateFrom, input.dateTo, JSON.stringify(input.filters), input.outputFormat])
	let id = inserted[0]?.id
	if (id) {
		await query(client, `insert into report_job_event(tenant_id,report_job_id,event_type,previous_state,new_state,attempt,actor_type,actor_id,dedupe_key)
			values($1,$2,'report.queued',null,'queued',0,'user',$3,'enqueue')`, [tenantId, id, userId])
	} else {
		const existing = await query<{ id: string }>(client, `select id from report_job where tenant_id=$1 and idempotency_key=$2
			and requested_by=$3 and date_from=$4 and date_to=$5 and filters=$6::jsonb and output_format=$7
			and definition_code='account-summary' and definition_version=1`, [tenantId, input.idempotencyKey, userId, input.dateFrom, input.dateTo, JSON.stringify(input.filters), input.outputFormat])
		if (!existing[0]) throw new ReportRequestError("idempotencyKey is already bound to another report scope", 409)
		id = existing[0].id
	}
	return getReport(client, tenantId, id)
}

export async function retryReport(client: PoolClient, tenantId: string, userId: string, role: TenantRole, jobId: string): Promise<ReportView> {
	if (!mayRequestReports(role)) throw new ReportRequestError("your tenant role cannot retry reports", 403)
	if (!UUID.test(jobId)) throw new ReportRequestError("invalid report id")
	const rows = await query<{ id: string; attempt: number }>(client, `update report_job set status='queued',queued_at=now(),next_attempt_at=now(),
		started_at=null,finished_at=null,worker_id=null,error=null where tenant_id=$1 and id=$2
		and status='failed' and attempt<max_attempts returning id,attempt`, [tenantId, jobId])
	if (!rows[0]) throw new ReportRequestError("report is not retryable", 409)
	await query(client, `insert into report_job_event(tenant_id,report_job_id,event_type,previous_state,new_state,attempt,actor_type,actor_id,dedupe_key)
		values($1,$2,'report.retry_queued','failed','queued',$3,'user',$4,$5)`, [tenantId, jobId, rows[0].attempt, userId, `attempt:${rows[0].attempt}:retry`])
	return getReport(client, tenantId, jobId)
}

export async function authorizedArtifact(client: PoolClient, tenantId: string, jobId: string): Promise<ArtifactDownload> {
	if (!UUID.test(jobId)) throw new ReportRequestError("invalid report id")
	const rows = await query<ArtifactDownload>(client, `select a.storage_key,a.content_sha256,a.media_type,a.file_extension,a.byte_size
		from report_artifact a join report_job j on j.id=a.report_job_id and j.tenant_id=a.tenant_id
		where a.tenant_id=$1 and a.report_job_id=$2 and j.status='succeeded' and a.expires_at>now()`, [tenantId, jobId])
	if (!rows[0]) throw new ReportRequestError("report artifact is missing or expired", 410)
	return rows[0]
}

export async function readAuthorizedArtifact(artifact: ArtifactDownload): Promise<Uint8Array> {
	const configuredRoot = process.env.REPORT_ARTIFACT_ROOT
	if (!configuredRoot) throw new ReportRequestError("private artifact storage is unavailable", 503)
	const root = resolve(configuredRoot)
	const path = resolve(root, artifact.storage_key)
	if (path !== root && !path.startsWith(`${root}${sep}`)) throw new ReportRequestError("invalid private artifact key", 500)
	let bytes: Buffer
	try { bytes = await readFile(path) } catch { throw new ReportRequestError("report artifact is unavailable", 410) }
	if (bytes.length !== Number(artifact.byte_size) || createHash("sha256").update(bytes).digest("hex") !== artifact.content_sha256) throw new ReportRequestError("report artifact failed integrity verification", 409)
	return new Uint8Array(bytes)
}
