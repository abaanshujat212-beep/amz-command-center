/**
 * Read model for search-term isolation and revive recommendations (R07.4).
 *
 * search_term_lifecycle_recommendation is a public table with FORCE RLS, so
 * withTenant() scopes every read. Rows are append-only evidence written by
 * services/rules/isolation_revive.py; nothing here writes or queues actions.
 */

import type { PoolClient } from "pg"
import { query } from "./db"

export type LifecycleType = "isolation_negative" | "revive_target"
export type LifecycleDecision = "recommended" | "blocked"

export type LifecycleRun = {
	run_id: string
	created_at: string
	data_through: string
}

export type LifecycleRow = {
	id: string
	recommendation_type: LifecycleType
	decision: LifecycleDecision
	blocked_reason: string | null
	campaign_id: string
	ad_group_id: string
	keyword_id: string | null
	term: string
	match_type: string
	current_bid: number | null
	proposed_bid: number | null
	evidence: Record<string, unknown>
}

export async function latestLifecycleRun(client: PoolClient): Promise<LifecycleRun | null> {
	const rows = await query<LifecycleRun>(
		client,
		`select run_id::text, max(created_at)::text as created_at, max(data_through)::text as data_through
		   from search_term_lifecycle_recommendation
		  group by run_id
		  order by max(created_at) desc
		  limit 1`,
	)
	return rows[0] ?? null
}

export async function lifecycleRecommendations(
	client: PoolClient,
	runId: string,
	type: LifecycleType | null = null,
	decision: LifecycleDecision | null = null,
): Promise<LifecycleRow[]> {
	return query<LifecycleRow>(
		client,
		`select id::text, recommendation_type, decision, blocked_reason, campaign_id, ad_group_id,
		        keyword_id, term, match_type, current_bid, proposed_bid, evidence
		   from search_term_lifecycle_recommendation
		  where run_id = $1
		    and ($2::text is null or recommendation_type = $2)
		    and ($3::text is null or decision = $3)
		  order by recommendation_type, decision desc, term, campaign_id, ad_group_id`,
		[runId, type, decision],
	)
}

export function parseLifecycleType(value: string | null | undefined): LifecycleType | null {
	return value === "isolation_negative" || value === "revive_target" ? value : null
}

export function parseLifecycleDecision(value: string | null | undefined): LifecycleDecision | null {
	return value === "recommended" || value === "blocked" ? value : null
}
