"use server"

import {revalidatePath} from "next/cache"
import {query, withTenant} from "@/lib/db"
import {currentContext} from "@/lib/session"
import {canReviewBiddingPlan, reviewBiddingPlan, type BiddingEvidence} from "@/lib/bidding-control-plan"

const value=(form:FormData,key:string)=>String(form.get(key)??"").trim()
const isUuid=(id:string)=>/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id)

async function captureReview(form:FormData, approval:boolean) {
  const actor=await currentContext()
  if (!canReviewBiddingPlan(actor.role)) throw new Error("Only owners and admins can manage this review.")
  const campaignId=value(form,"campaignId"), reason=value(form,"reason")
  const ref=value(form,approval?"proposalId":"evidenceId")
  if (!/^[0-9]{1,40}$/.test(campaignId)||!reason||reason.length>400||!isUuid(ref)) throw new Error("Campaign, review reference and reason are required.")
  const entity='campaign:'+campaignId
  await withTenant(actor.tenantId, async c=>{
    // Serialize audit decisions within this tenant/campaign. The transaction releases the lock.
    await query(c,"select pg_advisory_xact_lock(hashtextextended($1,0))",["bidding-control-review:"+actor.tenantId+":"+campaignId])
    const [snapshot]=await query<BiddingEvidence>(c,`select id::text,bidding_strategy,bidding_strategy_supported,
      rule_based_bidding_active,cost_control_active,source_observed_at::text,source_api_version
      from campaign_native_control_state where tenant_id=$1 and campaign_id=$2
      order by source_observed_at desc,loaded_at desc,id desc limit 1`,[actor.tenantId,campaignId])
    const plan=reviewBiddingPlan(snapshot,Date.now())
    if (!plan.allowed) throw new Error(plan.reason)
    let proposalId:string|undefined
    if (approval) {
      const [proposal]=await query<{actor_user_id:string;evidence_id:string}>(c,`select actor_user_id::text,
        after->>'evidenceId' evidence_id from audit_log
        where tenant_id=$1 and entity=$2 and id=$3::uuid and action='bidding_control.review_proposed'`,[actor.tenantId,entity,ref])
      if (!proposal||!proposal.actor_user_id||proposal.actor_user_id===actor.userId||proposal.evidence_id!==plan.evidenceId)
        throw new Error("Review requires another owner or admin and the original current evidence.")
      proposalId=ref
    } else if (ref!==plan.evidenceId) throw new Error("Amazon evidence changed. Refresh the preview before requesting review.")
    const event=approval?'bidding_control.review_approved':'bidding_control.review_proposed'
    const key=approval?'proposalId':'evidenceId'
    const [prior]=await query<{id:string}>(c,`select id::text from audit_log
      where tenant_id=$1 and entity=$2 and action=$3 and after->>($4::text)=$5 limit 1`,
      [actor.tenantId,entity,event,key,proposalId??plan.evidenceId])
    if (prior) return
    await query(c,`insert into audit_log(tenant_id,actor_user_id,action,entity,before,after)
      values($1,$2,$3,$4,$5::jsonb,$6::jsonb)`,[actor.tenantId,actor.userId,event,entity,
      JSON.stringify(plan.before),JSON.stringify({...plan.after,mode:plan.mode,evidenceId:plan.evidenceId,proposalId,reason,applied:false})])
  })
  revalidatePath("/campaigns/"+campaignId)
  revalidatePath("/settings/audit")
}

export async function proposeBiddingControlReview(form:FormData){await captureReview(form,false)}
export async function approveBiddingControlReview(form:FormData){await captureReview(form,true)}
