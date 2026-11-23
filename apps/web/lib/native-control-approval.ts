import type { PoolClient } from "pg";
import { query } from "@/lib/db";

type NativeControlApprovalRow = {
  action_type: string;
  entity_type: string;
  campaign_id: string | null;
  bidding_strategy: string | null;
  bidding_strategy_supported: boolean | null;
  budget_rule_active: boolean | null;
  schedule_rule_active: boolean | null;
  rule_based_bidding_active: boolean | null;
  cost_control_active: boolean | null;
  source_observed_at: string | null;
};

const guarded = new Set([
  "keyword:set_bid", "target:set_bid", "ad_group:set_bid",
  "search_term:create_keyword",
  "campaign:set_placement_modifier", "campaign:set_budget",
  "campaign:pause", "campaign:enable",
]);

export async function nativeControlApprovalConflict(client: PoolClient, actionId: string): Promise<string | null> {
  const rows = await query<NativeControlApprovalRow>(client, `
    select a.action_type,a.entity_type,
      coalesce(nullif(a.after_value->>'campaign_id',''),nullif(a.before_value->>'campaign_id',''),nullif(e.metrics_snapshot->>'campaign_id',''),case when a.entity_type='campaign' then a.entity_id end) campaign_id,
      n.bidding_strategy,n.bidding_strategy_supported,n.budget_rule_active,n.schedule_rule_active,
      n.rule_based_bidding_active,n.cost_control_active,n.source_observed_at::text
    from action a left join rule_evaluation e on e.tenant_id=a.tenant_id and e.id=a.evaluation_id
    left join lateral(select s.* from campaign_native_control_state s where s.tenant_id=a.tenant_id and s.campaign_id=coalesce(nullif(a.after_value->>'campaign_id',''),nullif(a.before_value->>'campaign_id',''),nullif(e.metrics_snapshot->>'campaign_id',''),case when a.entity_type='campaign' then a.entity_id end) order by s.source_observed_at desc,s.loaded_at desc limit 1)n on true
    where a.id=$1`, [actionId]);
  const row=rows[0];
  if(!row||!guarded.has(`${row.entity_type}:${row.action_type}`)) return null;
  if(!row.campaign_id||!row.source_observed_at) return "NATIVE_CONTROL_EVIDENCE_MISSING: sync campaign native-control state before approval.";
  const observed=Date.parse(row.source_observed_at);
  if(!Number.isFinite(observed)||observed>Date.now()+5*60*1000) return "NATIVE_CONTROL_EVIDENCE_INVALID: campaign native-control timestamp is invalid.";
  if(Date.now()-observed>24*60*60*1000) return "NATIVE_CONTROL_EVIDENCE_STALE: refresh campaign native-control state before approval.";
  if(!row.bidding_strategy_supported) return `NATIVE_CONTROL_UNSUPPORTED: strategy ${row.bidding_strategy??"unknown"} is not verified.`;
  const bid=row.action_type==="set_bid"||row.action_type==="create_keyword";
  const placement=row.action_type==="set_placement_modifier";
  const budget=row.action_type==="set_budget";
  const campaignState=row.entity_type==="campaign"&&(row.action_type==="pause"||row.action_type==="enable");
  if(((bid||placement)&&(row.rule_based_bidding_active==null||row.cost_control_active==null))||(budget&&row.budget_rule_active==null)||(campaignState&&row.schedule_rule_active==null)) return "NATIVE_CONTROL_EVIDENCE_MISSING: required native-control state is unknown.";
  const conflict=(bid&&(row.bidding_strategy!=="fixed"||row.rule_based_bidding_active||row.cost_control_active))||(placement&&(row.rule_based_bidding_active||row.cost_control_active))||(budget&&row.budget_rule_active)||(campaignState&&row.schedule_rule_active);
  return conflict ? "NATIVE_OPTIMIZATION_CONFLICT: keep Amazon control or create a separately approved control-transfer proposal." : null;
}
