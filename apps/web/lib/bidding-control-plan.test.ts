import { strict as assert } from "node:assert"
import { test } from "node:test"
import { canReviewBiddingPlan,reviewBiddingPlan,type BiddingEvidence } from "./bidding-control-plan"

const now=Date.parse("2026-01-02T12:00Z")
const ready:BiddingEvidence={id:"immutable-id",bidding_strategy:"dynamic_down_only",bidding_strategy_supported:true,
  rule_based_bidding_active:false,cost_control_active:false,source_observed_at:"2026-01-02T11:00Z",source_api_version:"sp-campaigns-v3"}

test("dynamic strategies preserve the observed strategy and preview fixed only as a dry-run",()=>{
  for(const strategy of ["dynamic_down_only","dynamic_up_down"]){
    const plan=reviewBiddingPlan({...ready,bidding_strategy:strategy},now)
    assert.equal(plan.allowed,true)
    assert.equal(plan.before.strategy,strategy)
    assert.equal(plan.after.strategy,"fixed")
    assert.equal(plan.mode,"dry_run")
    assert.equal(plan.evidenceId,ready.id)
  }
})

test("fails closed on incomplete, future, stale, active, or unsupported evidence",()=>{
  for(const snapshot of [undefined,{...ready,bidding_strategy:"unsupported"},{...ready,bidding_strategy:"fixed"},
    {...ready,bidding_strategy_supported:false},{...ready,rule_based_bidding_active:true},
    {...ready,rule_based_bidding_active:null},{...ready,cost_control_active:true},{...ready,cost_control_active:null},
    {...ready,source_observed_at:"bad date"},{...ready,source_observed_at:"2026-01-01T11:59Z"},
    {...ready,source_observed_at:"2026-01-02T12:06Z"}]){
    assert.equal(reviewBiddingPlan(snapshot,now).allowed,false)
  }
})

test("only tenant owners and admins can request or review",()=>{
  for(const role of ["owner","admin"])assert.equal(canReviewBiddingPlan(role),true)
  for(const role of ["operator","viewer","member",""])assert.equal(canReviewBiddingPlan(role),false)
})
