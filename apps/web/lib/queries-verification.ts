import type { PoolClient } from "pg"
import { query } from "./db"

export type VerificationConfounder = {
	source: "manual" | "amazon_native" | "axaty"
	window: "baseline" | "after"
	change_kind: string
	source_ref: string | null
	changed_at: string
	action_id: string | null
	signal_id: string | null
}

export type VerificationSnapshot = {
	horizon_days: number
	status: "COMPLETE" | "INSUFFICIENT_DATA" | "FAILED"
	outcome: string | null
	metric_keys: string[]
	baseline: unknown
	observed: unknown
	data_through: string | null
	reason_code: string | null
	checked_at: string
	confounding_status: "CONFOUNDED" | "NO_RECORDED_CHANGES" | "PENDING"
	confounders: VerificationConfounder[]
	confounder_count: number
	evidence_truncated: boolean
}

export type VerificationScorecard = {
	id: string
	entity_type: string
	entity_id: string
	action_type: string
	status: string
	outcome: string | null
	applied_at: string | null
	verified_at: string | null
	before_value: unknown
	after_value: unknown
	impact_jsonb: unknown
	snapshots: VerificationSnapshot[]
	reason_text: string | null
	rule_code: string | null
	rule_name: string | null
}

export async function verificationScorecards(client: PoolClient, limit = 100): Promise<VerificationScorecard[]> {
	return query<VerificationScorecard>(client, `
		select a.id::text,a.entity_type,a.entity_id,a.action_type,a.status,a.outcome,
			a.applied_at::text,a.verified_at::text,a.before_value,a.after_value,a.impact_jsonb,
			a.reason_text,r.code as rule_code,r.name as rule_name,
			coalesce((
				select jsonb_agg(jsonb_build_object(
					'horizon_days',s.horizon_days,'status',s.status,'outcome',s.outcome,
					'metric_keys',s.metric_keys,'baseline',s.baseline_metrics,'observed',s.observed_metrics,
					'data_through',s.data_through,'reason_code',s.reason_code,'checked_at',s.checked_at,
					'confounding_status',c.confounding_status,'confounders',c.confounders,
					'confounder_count',c.confounder_count,'evidence_truncated',c.evidence_truncated
				) order by s.horizon_days)
				from action_verification_snapshot s
				cross join lateral verification_confounding_evidence(a.tenant_id,s.action_id,s.horizon_days) c
				where s.tenant_id=a.tenant_id and s.action_id=a.id
			),'[]'::jsonb) snapshots
		from action a left join rule r on r.id=a.rule_id
		where a.tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid
			and a.status in ('applied','verified') and a.action_type<>'flag'
		order by coalesce(a.verified_at,a.applied_at,a.requested_at) desc limit $1`, [limit])
}
