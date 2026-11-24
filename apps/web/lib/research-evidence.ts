export type StoredEvidence = {
  completeness: string
  numeric_value: string | null
  text_value: string | null
  unit: string | null
  observed_at: string
  provider: string
  method: string
  evidence_ref: string
  evidence_scope: unknown
}

const scopeKeys = ["marketplace", "marketplace_id", "country", "grain", "period", "window", "currency", "channel"] as const
const clean = (value: unknown, limit: number) =>
  typeof value === "string" ? value.trim().slice(0, limit) : ""

function safeReference(value: unknown) {
  const raw = clean(value, 300)
  // Provider references are plain text, never clickable. Do not display a
  // signed URL, user information, fragments, or arbitrary credential text.
  if (/^https?:\/\//i.test(raw)) {
    try {
      const url = new URL(raw)
      return url.hostname ? url.origin : ""
    } catch { return "" }
  }
  return /^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$/.test(raw) ? raw : ""
}

export function presentResearchEvidence(row: StoredEvidence, now: number) {
  const scope = typeof row.evidence_scope === "object" && row.evidence_scope !== null && !Array.isArray(row.evidence_scope)
    ? row.evidence_scope as Record<string, unknown> : {}
  const dimensions = scopeKeys.flatMap(key => {
    const value = Object.hasOwn(scope, key) ? clean(scope[key], 80) : ""
    return value ? [{ key, value }] : []
  })
  const observed = Date.parse(row.observed_at)
  const observationTimeValid = Number.isFinite(observed) && observed <= now
  const provider = clean(row.provider, 160), method = clean(row.method, 160), source = safeReference(row.evidence_ref)
  const singleValue = (row.numeric_value === null) !== (row.text_value === null)
  const numeric = row.numeric_value === null ? "" : clean(row.numeric_value, 100)
  const text = row.text_value === null ? "" : clean(row.text_value, 300)
  // Numeric strings preserve PostgreSQL precision and distinguish zero from no value.
  const value = numeric && /^[-+]?\d+(?:\.\d+)?$/.test(numeric) ? numeric : text
  const quality = row.completeness === "blocked" ? "Blocked" : row.completeness === "partial" ? "Partial" :
    row.completeness === "complete" && provider && method && source && observationTimeValid &&
    dimensions.length && singleValue && value ? "Complete as recorded" : "Unverified provenance"
  return {
    provider, method, source, dimensions, observationTimeValid, quality,
    value: quality === "Complete as recorded" ? value : null,
    unit: quality === "Complete as recorded" ? clean(row.unit, 30) : "",
  }
}
