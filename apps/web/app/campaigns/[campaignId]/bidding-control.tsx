import Link from "next/link"
import {query, withTenant} from "@/lib/db"
import {currentContext} from "@/lib/session"
import {canReviewBiddingPlan, reviewBiddingPlan, type BiddingEvidence} from "@/lib/bidding-control-plan"
import {proposeBiddingControlReview, approveBiddingControlReview} from "./bidding-control-actions"

export async function BiddingControlPanel({campaignId}: {campaignId: string}) {
  const actor = await currentContext()
  const canManage = canReviewBiddingPlan(actor.role)
  const {snapshot, reviews} = await withTenant(actor.tenantId, async c => ({
    snapshot: (await query<BiddingEvidence>(c,`select id::text,bidding_strategy,bidding_strategy_supported,
      rule_based_bidding_active,cost_control_active,source_observed_at::text,source_api_version
      from campaign_native_control_state where tenant_id=$1 and campaign_id=$2
      order by source_observed_at desc,loaded_at desc,id desc limit 1`,[actor.tenantId,campaignId]))[0],
    reviews: canManage ? await query<{id:string;actor_user_id:string;at:string;evidence_id:string;before_strategy:string;after_strategy:string;approved:boolean}>(c,`
      select p.id::text,p.actor_user_id::text,p.at::text,p.after->>'evidenceId' evidence_id,
      p.before->>'strategy' before_strategy,p.after->>'strategy' after_strategy,
      exists(select 1 from audit_log q where q.tenant_id=p.tenant_id and q.entity=p.entity
        and q.action='bidding_control.review_approved' and q.after->>'proposalId'=p.id::text) approved
      from audit_log p where p.tenant_id=$1 and p.entity=$2 and p.action='bidding_control.review_proposed'
      order by p.at desc,p.id desc limit 5`,[actor.tenantId,'campaign:'+campaignId]) : [],
  }))
  const plan = reviewBiddingPlan(snapshot, Date.now())
  return <section className="space-y-3 rounded-xl border bg-white p-4">
    <h2 className="font-semibold">Bidding strategy and ownership</h2>
    <p className="text-sm">Current Amazon strategy: <strong>{snapshot?.bidding_strategy ?? "Unknown"}</strong>
      {snapshot ? <> · Evidence {snapshot.source_observed_at} ({snapshot.source_api_version})</> : null}</p>
    <p className="text-sm text-slate-600">Keep Amazon control to leave this campaign unchanged. A separate reviewer can approve a dry-run plan only. No Amazon setting, ownership, bid, budget, placement, or existing proposal changes here.</p>
    {plan.allowed ? <div className="grid gap-3 rounded border p-3 text-sm sm:grid-cols-2">
      <div><strong>Before</strong><div>{plan.before.strategy} · {plan.before.owner}</div></div>
      <div><strong>Proposed only</strong><div>{plan.after.strategy} · {plan.after.owner}</div></div>
    </div> : <p className="text-sm text-amber-800">{plan.reason}</p>}
    {plan.allowed && canManage && !reviews.some(r=>r.evidence_id===plan.evidenceId) ? <form action={proposeBiddingControlReview} className="flex flex-wrap gap-2">
      <input type="hidden" name="campaignId" value={campaignId}/>
      <input type="hidden" name="evidenceId" value={plan.evidenceId}/>
      <input required name="reason" maxLength={400} aria-label="Control review reason" placeholder="Reason for review" className="rounded border px-2 py-1"/>
      <button className="rounded bg-slate-900 px-3 py-1 text-white">Request dry-run review</button>
    </form> : null}
    {reviews.map(review=><div key={review.id} className="space-y-2 rounded border p-3 text-sm">
      <div>{review.approved ? "Dry-run reviewed. Nothing applied." : review.evidence_id !== snapshot?.id || !plan.allowed ? "Review expired or blocked." : "Awaiting a different owner or admin."} · {review.at}</div>
      <div>{review.before_strategy} → {review.after_strategy} (dry-run only)</div>
      {plan.allowed && !review.approved && review.evidence_id===plan.evidenceId && review.actor_user_id!==actor.userId ? <form action={approveBiddingControlReview} className="flex flex-wrap gap-2">
        <input type="hidden" name="campaignId" value={campaignId}/>
        <input type="hidden" name="proposalId" value={review.id}/>
        <input required name="reason" maxLength={400} aria-label="Review decision reason" placeholder="Decision reason" className="rounded border px-2 py-1"/>
        <button className="rounded border px-3 py-1">Approve dry-run only</button>
      </form> : null}
    </div>)}
    {canManage ? <Link href="/settings/audit?action=bidding_control." className="text-sm text-blue-700 hover:underline">Review audit history</Link> : null}
  </section>
}
