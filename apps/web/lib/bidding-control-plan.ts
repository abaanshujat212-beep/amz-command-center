export type BiddingEvidence = {
  id: string
  bidding_strategy: string
  bidding_strategy_supported: boolean
  rule_based_bidding_active: boolean | null
  cost_control_active: boolean | null
  source_observed_at: string
  source_api_version: string
}

export function canReviewBiddingPlan(role: string): boolean {
  return role === "owner" || role === "admin"
}

export function reviewBiddingPlan(snapshot: BiddingEvidence | undefined, now: number) {
  if (!snapshot) return {allowed:false as const, reason:"No Amazon bidding-strategy evidence."}
  const observed = Date.parse(snapshot.source_observed_at)
  if (!Number.isFinite(observed) || observed > now + 5 * 60_000 || now - observed > 24 * 60 * 60_000) {
    return {allowed:false as const, reason:"Current Amazon evidence is missing, stale, or invalid."}
  }
  if (!snapshot.bidding_strategy_supported || !["fixed","dynamic_down_only","dynamic_up_down"].includes(snapshot.bidding_strategy)) {
    return {allowed:false as const, reason:"This Amazon bidding strategy is preserved but unsupported."}
  }
  if (snapshot.rule_based_bidding_active !== false || snapshot.cost_control_active !== false) {
    return {allowed:false as const, reason:"Amazon rule-based bidding or cost control is active or unverified. Keep Amazon control."}
  }
  if (snapshot.bidding_strategy === "fixed") {
    return {allowed:false as const, reason:"Already fixed. There is no dynamic bid control to transfer."}
  }
  return {allowed:true as const, before:{strategy:snapshot.bidding_strategy,owner:"Amazon dynamic bidding"},
    after:{strategy:"fixed",owner:"Eligible for separately authorized managed bids"},
    evidenceId:snapshot.id, mode:"dry_run" as const}
}
