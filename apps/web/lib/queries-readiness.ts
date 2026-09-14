import type { PoolClient } from "pg"
import { query } from "@/lib/db"

export type DependencyReadiness = {
	marketplace_id: string
	module_key: string
	dependency_key: string
	readiness_state: string
	reason_code: string | null
	evidence_source: string | null
	evidence_observed_at: string | null
	evidence_expires_at: string | null
}

export type ModuleState = {
	marketplace_id: string
	module_key: string
	entitlement_state: string
	visibility_state: string
	reason_code: string | null
}

export async function readinessSnapshot(client: PoolClient) {
	const dependencies = await query<DependencyReadiness>(client,
		`select marketplace_id, module_key, dependency_key, readiness_state, reason_code,
		 evidence_source, evidence_observed_at, evidence_expires_at
		 from external_dependency_state order by module_key, dependency_key`)
	const modules = await query<ModuleState>(client,
		`select marketplace_id, module_key, entitlement_state, visibility_state, reason_code
		 from module_state order by module_key`)
	return { dependencies, modules }
}
