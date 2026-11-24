const TYPES = new Set(["bid_adjustment", "budget_adjustment", "entity_state", "negative_targeting", "keyword_harvest", "placement_adjustment", "diagnostic"])
const STATUSES = new Set(["pending", "approved", "applied", "verified", "rejected", "expired", "failed", "rolled_back"])
const RISKS = new Set(["low", "medium", "high", "critical"])
const MAX_OFFSET = 2_147_483_647

export class RecommendationQueryError extends Error {
	constructor(message: string, readonly status = 400) { super(message) }
}

export type RecommendationFilters = {
	type?: string; status?: string; risk?: string; entityType?: string; entityId?: string
	from?: string; to?: string; confidence?: number; minConfidence?: number; limit: number; offset: number
}

function one(raw: string | null, set: Set<string>, name: string) {
	if (!raw) return undefined
	if (!set.has(raw)) throw new RecommendationQueryError(`invalid ${name}`)
	return raw
}

function date(raw: string | null) {
	if (!raw) return undefined
	const parsed = Date.parse(raw)
	if (!/^\d{4}-\d{2}-\d{2}$/.test(raw) || raw.startsWith("0000") || !Number.isFinite(parsed)
		|| new Date(parsed).toISOString().slice(0,10) !== raw) {
		throw new RecommendationQueryError("dates must be valid calendar dates (YYYY-MM-DD)")
	}
	return raw
}

function confidence(raw: string | null) {
	if (!raw?.trim()) return undefined
	const score = Number(raw)
	if (!Number.isFinite(score) || score < 0 || score > 1) throw new RecommendationQueryError("confidence must be between 0 and 1")
	return score
}

export function parseRecommendationFilters(params: URLSearchParams): RecommendationFilters {
	const offset = Number(params.get("offset") ?? 0)
	const desiredLimit = Number(params.get("limit") ?? 50)
	if (!Number.isSafeInteger(desiredLimit) || !Number.isSafeInteger(offset) || offset < 0 || offset > MAX_OFFSET) {
		throw new RecommendationQueryError("invalid pagination")
	}
	const limit = Math.min(100, Math.max(1, desiredLimit))
	const from = date(params.get("from")), to = date(params.get("to"))
	if (from && to && from > to) throw new RecommendationQueryError("start date must not follow end date")
	return {
		type: one(params.get("type"), TYPES, "type"), status: one(params.get("status"), STATUSES, "status"),
		risk: one(params.get("risk"), RISKS, "risk"), entityType: params.get("entityType")?.trim() || undefined,
		entityId: params.get("entityId")?.trim() || undefined, from, to, confidence: confidence(params.get("confidence")),
		minConfidence: confidence(params.get("minConfidence")), limit, offset,
	}
}

export function recommendationPage<T>(rows: T[], {limit, offset}: RecommendationFilters) {
	const recommendations = rows.slice(0, limit)
	return {
		recommendations,
		pagination: {limit, offset, count: recommendations.length,
			previousOffset: offset ? Math.max(0, offset - limit) : null,
			nextOffset: rows.length > limit && offset + limit <= MAX_OFFSET ? offset + limit : null},
	}
}

export function recommendationPageHref(params: URLSearchParams, offset: number) {
	const query = new URLSearchParams(params)
	if (offset) query.set("offset", String(offset))
	else query.delete("offset")
	return `/recommendations${query.size ? `?${query}` : ""}`
}

export function confidenceLabel(score: number | null) {
	return score == null ? "Confidence not available" : `${Math.round(score * 100)}% confidence`
}
