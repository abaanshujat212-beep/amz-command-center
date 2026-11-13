import type { PoolClient, QueryResultRow } from "pg"
import { query, type TenantRole } from "@/lib/db"

export class ExperimentInputError extends Error {
	constructor(message: string, public status = 400) { super(message) }
}

type Experiment = QueryResultRow & {
	id: string; name: string; hypothesis: string; success_metric: string; control_description: string
	entity_type: string; entity_id: string; start_date: string; end_date: string | null
	status: string; summary: string | null; created_at: string; outcome_count: number
	improved_count: number; worsened_count: number; mean_metric_value: number | null; mean_sample_size: number | null
	success_rate: number | null; outcomes: {id:string;outcome:string;metric_name:string;metric_value:number|null;sample_size:number|null;observed_at:string;evidence_note:string;outcome_kind:string;action_id:string|null;horizon_days:number|null}[]
}
const text = (value: unknown, name: string, max: number) => {
	if (typeof value !== "string" || !value.trim() || value.trim().length > max) throw new ExperimentInputError(`${name} must be a non-empty string of at most ${max} characters.`)
	return value.trim()
}
const date = (value: unknown, name: string) => {
	if (typeof value !== "string" || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`)) || new Date(`${value}T00:00:00Z`).toISOString().slice(0,10) !== value) throw new ExperimentInputError(`${name} must be an ISO calendar date.`)
	return value
}
function manager(role: TenantRole) { if (role !== "owner" && role !== "admin") throw new ExperimentInputError("owner_or_admin_required", 403) }

export async function listActionExperiments(client: PoolClient, tenantId: string) {
	return query<Experiment>(client, `select e.id::text,e.name,e.hypothesis,e.success_metric,e.control_description,
		e.entity_type,e.entity_id,e.start_date::text,e.end_date::text,e.status,e.summary,e.created_at::text,
		count(o.id)::int outcome_count,count(o.id) filter(where o.outcome='improved')::int improved_count,
		count(o.id) filter(where o.outcome='worsened')::int worsened_count,
		avg(o.metric_value)::float8 mean_metric_value,avg(o.sample_size)::float8 mean_sample_size,
		count(o.id) filter(where o.metric_name=e.success_metric and o.outcome='improved')::float8/nullif(count(o.id) filter(where o.metric_name=e.success_metric and o.outcome in ('improved','worsened','neutral')),0) success_rate,
		coalesce((select jsonb_agg(jsonb_build_object('metric_name',m.metric_name,'outcome_count',m.outcome_count,
			'mean_metric_value',m.mean_metric_value,'mean_sample_size',m.mean_sample_size) order by m.metric_name)
			from (select metric_name,count(*)::int outcome_count,avg(metric_value)::float8 mean_metric_value,
				avg(sample_size)::float8 mean_sample_size from action_experiment_outcome
				where tenant_id=e.tenant_id and experiment_id=e.id group by metric_name) m),'[]'::jsonb) metric_summaries,
		coalesce(jsonb_agg(jsonb_build_object('id',o.id::text,'outcome',o.outcome,'metric_name',o.metric_name,
			'metric_value',o.metric_value,'sample_size',o.sample_size,'observed_at',o.observed_at::text,
			'evidence_note',o.evidence_note,'outcome_kind',o.outcome_kind,'action_id',o.action_id::text,'horizon_days',o.horizon_days)
			order by o.observed_at desc,o.id desc) filter(where o.id is not null),'[]'::jsonb) outcomes
		from action_experiment e left join action_experiment_outcome o on o.tenant_id=e.tenant_id and o.experiment_id=e.id
		where e.tenant_id=$1 group by e.id order by e.created_at desc,e.id desc limit 100`, [tenantId])
}

export async function createActionExperiment(client: PoolClient, tenantId: string, userId: string, role: TenantRole, raw: unknown) {
	manager(role)
	if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new ExperimentInputError("An experiment object is required.")
	const value = raw as Record<string, unknown>, startDate = date(value.startDate, "startDate")
	if (Object.keys(value).some(key => !["name","hypothesis","successMetric","controlDescription","entityType","entityId","startDate"].includes(key))) throw new ExperimentInputError("Unsupported experiment field.")
	const row = (await query<Experiment>(client, `insert into action_experiment
		(tenant_id,name,hypothesis,success_metric,control_description,entity_type,entity_id,start_date,created_by)
		values($1,$2,$3,$4,$5,$6,$7,$8,$9) returning id::text,name,hypothesis,success_metric,control_description,
		entity_type,entity_id,start_date::text,end_date::text,status,summary,created_at::text,0::int outcome_count,
		0::int improved_count,0::int worsened_count,null::float8 mean_metric_value,null::float8 mean_sample_size`,
	[tenantId,text(value.name,"name",160),text(value.hypothesis,"hypothesis",4000),text(value.successMetric,"successMetric",120),
		text(value.controlDescription,"controlDescription",2000),text(value.entityType,"entityType",80),text(value.entityId,"entityId",200),startDate,userId]))[0]
	await query(client, "insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'action_experiment.created',$3,$4::jsonb)", [tenantId,userId,`action_experiment:${row.id}`,JSON.stringify({name:row.name,entityType:row.entity_type,entityId:row.entity_id,startDate})])
	return row
}

export async function addExperimentOutcome(client: PoolClient, tenantId: string, userId: string, role: TenantRole, raw: unknown) {
	manager(role)
	if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new ExperimentInputError("An outcome object is required.")
	const value = raw as Record<string, unknown>, experimentId = text(value.experimentId,"experimentId",36)
	if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(experimentId)) throw new ExperimentInputError("experimentId must be a UUID.")
	if (Object.keys(value).some(key => !["experimentId","metricName","outcome","observedAt","metricValue","sampleSize","actionId","horizonDays","evidenceNote"].includes(key))) throw new ExperimentInputError("Unsupported outcome field.")
	const experiment = (await query<{entity_type:string;entity_id:string;status:string;start_date:string;end_date:string|null}>(client,"select entity_type,entity_id,status,start_date::text,end_date::text from action_experiment where tenant_id=$1 and id=$2::uuid for update",[tenantId,experimentId]))[0]
	if (!experiment) throw new ExperimentInputError("Experiment not found.",404)
	if (experiment.status === "completed" || experiment.status === "cancelled") throw new ExperimentInputError("Terminal experiments cannot accept more outcomes.",409)
	const metricName=text(value.metricName,"metricName",120), outcome=value.outcome
	const definition=(await query<{success_metric:string}>(client,"select success_metric from action_experiment where tenant_id=$1 and id=$2::uuid",[tenantId,experimentId]))[0]
	if (metricName !== definition?.success_metric) throw new ExperimentInputError("Outcome metricName must match the experiment success metric.")
	if (!new Set(["improved","worsened","neutral","inconclusive","confounded"]).has(String(outcome))) throw new ExperimentInputError("Unsupported outcome.")
	const observedAt = value.observedAt === undefined ? new Date().toISOString() : value.observedAt
	if (typeof observedAt !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(observedAt) || !Number.isFinite(Date.parse(observedAt))) throw new ExperimentInputError("observedAt must be an ISO timestamp with a timezone.")
	const observedDay = new Date(observedAt).toISOString().slice(0,10)
	if (observedDay < experiment.start_date || experiment.end_date && observedDay > experiment.end_date) throw new ExperimentInputError("Outcome observation must fall within the experiment dates.")
	const metric = value.metricValue === undefined || value.metricValue === null ? null : Number(value.metricValue)
	const sample = value.sampleSize === undefined || value.sampleSize === null ? null : Number(value.sampleSize)
	if (metric !== null && !Number.isFinite(metric)) throw new ExperimentInputError("metricValue must be finite or null.")
	if (sample !== null && (!Number.isSafeInteger(sample) || sample < 0)) throw new ExperimentInputError("sampleSize must be a non-negative integer or null.")
	let actionId: string | null = null, horizon: number | null = null, kind: "verified_action" | "operator_observation" = "operator_observation"
	if (value.actionId !== undefined && value.actionId !== null) {
		actionId=text(value.actionId,"actionId",36); horizon=Number(value.horizonDays)
		if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(actionId)) throw new ExperimentInputError("actionId must be a UUID.")
		if (![1,3,7,14,30].includes(horizon)) throw new ExperimentInputError("horizonDays must be one of 1, 3, 7, 14 or 30.")
		const evidence=(await query<{confounding_status:string;status:string;outcome:string|null;entity_type:string;entity_id:string;applied_at:string|null}>(client,`select s.status,s.outcome,c.confounding_status,a.entity_type,a.entity_id,a.applied_at::text from action_verification_snapshot s
			join action a on a.tenant_id=s.tenant_id and a.id=s.action_id
			cross join lateral verification_confounding_evidence($1,$2,$3) c
			where s.tenant_id=$1 and s.action_id=$2::uuid and s.horizon_days=$3`,[tenantId,actionId,horizon]))[0]
		if (!evidence) throw new ExperimentInputError("A completed verification snapshot for that action and horizon is required.")
		if (evidence.entity_type !== experiment.entity_type || evidence.entity_id !== experiment.entity_id) throw new ExperimentInputError("Linked action must target the experiment entity.")
		if (!evidence.applied_at || evidence.applied_at.slice(0,10) < experiment.start_date || experiment.end_date && evidence.applied_at.slice(0,10) > experiment.end_date) throw new ExperimentInputError("Linked action must have been applied during the experiment.")
		if (evidence.confounding_status === "CONFOUNDED" || outcome !== evidence.outcome) throw new ExperimentInputError("Recorded action outcome must match its unconfounded verification snapshot.")
		if (evidence.status !== "COMPLETE") throw new ExperimentInputError("Only complete verification snapshots can be linked.")
		kind="verified_action"
	}
	const evidenceNote=text(value.evidenceNote,"evidenceNote",4000)
	const row=(await query<{id:string}>(client,`insert into action_experiment_outcome(tenant_id,experiment_id,action_id,horizon_days,outcome_kind,outcome,metric_name,metric_value,sample_size,observed_at,evidence_note,created_by)
		values($1,$2::uuid,$3::uuid,$4,$5,$6,$7,$8,$9,$10::timestamptz,$11,$12) returning id::text`,[tenantId,experimentId,actionId,horizon,kind,outcome,metricName,metric,sample,new Date(observedAt).toISOString(),evidenceNote,userId]))[0]
	await query(client,"insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,'action_experiment.outcome_recorded',$3,$4::jsonb)",[tenantId,userId,`action_experiment:${experimentId}`,JSON.stringify({outcomeId:row.id,outcome,metricName,actionId,horizon,kind})])
	return row
}
