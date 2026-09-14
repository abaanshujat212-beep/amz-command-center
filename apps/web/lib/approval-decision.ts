import { liveActionSupport } from "@/lib/action-support";
import { query, withTenant } from "@/lib/db";

type Decision = "approved" | "rejected";
export class ApprovalDecisionError extends Error {
  constructor(
    message: string,
    public status = 400,
  ) {
    super(message);
  }
}

type Candidate = {
  id: string;
  entity_type: string;
  entity_id: string;
  action_type: string;
};

type Collision = {
  collision_kind: string;
  evidence: unknown;
};

const collisionMessages: Record<string, string> = {
  active_action: "Another active financial action already owns this entity.",
  manual_change: "A recent manual change conflicts with this proposal.",
  amazon_native_change: "Amazon-native automation currently owns this entity.",
  recent_axaty_change:
    "A recent AXATY change is still inside the collision window.",
};

export async function decideAction(input: {
  tenantId: string;
  userId: string;
  role: string;
  actionId: string;
  decision: Decision;
}) {
  if (input.role !== "owner" && input.role !== "admin") {
    throw new ApprovalDecisionError(
      "Only tenant owners and admins can approve Amazon actions.",
      403,
    );
  }
  const isApproval = input.decision === "approved";
  await withTenant(input.tenantId, async (c) => {
    if (isApproval) {
      const candidate = await query<Candidate>(
        c,
        "select id, entity_type, entity_id, action_type from action where id = $1 and status = 'pending'",
        [input.actionId],
      );
      if (candidate.length > 0) {
        const readiness = await query<{
          readiness_state: string;
          verification_level: string | null;
        }>(
          c,
          "select readiness_state, metadata->>'verification_level' as verification_level from external_dependency_state where module_key = 'ppc' and dependency_key = 'amazon_ads' order by updated_at desc limit 1",
        );
        const state = readiness[0];
        const support = liveActionSupport(
          candidate[0].entity_type,
          candidate[0].action_type,
          state?.readiness_state,
          state?.verification_level ?? undefined,
        );
        if (!support.supported) {
          throw new ApprovalDecisionError(support.message, 409);
        }

        const collisions = await query<Collision>(
          c,
          "select collision_kind, evidence from detect_action_collision($1::uuid,$2,$3,$4::uuid,now())",
          [
            input.tenantId,
            candidate[0].entity_type,
            candidate[0].entity_id,
            candidate[0].id,
          ],
        );
        if (collisions.length > 0) {
          const kind = collisions[0].collision_kind;
          throw new ApprovalDecisionError(
            collisionMessages[kind] ??
              "A conflicting entity change blocks approval.",
            409,
          );
        }
      }
    }
    const rows = await query<{
      id: string;
      entity_type: string;
      entity_id: string;
      action_type: string;
      before_value: unknown;
      after_value: unknown;
      decided_at: string;
    }>(
      c,
      `update action set status=$2, decision=$2, decided_by=$3, decided_at=now(), approved_by=case when $4::boolean then $3::uuid else approved_by end, approved_at=case when $4::boolean then now() else approved_at end where id=$1 and status='pending' and expires_at > now() and action_type <> 'flag' returning id, entity_type, entity_id, action_type, before_value, after_value, decided_at::text as decided_at`,
      [input.actionId, input.decision, input.userId, isApproval],
    );
    if (rows.length === 0) {
      const existing = await query<{
        status: string;
        expired: boolean;
        kind: string;
      }>(
        c,
        "select status, (expires_at <= now()) as expired, action_type as kind from action where id = $1",
        [input.actionId],
      );
      if (existing.length === 0) {
        throw new ApprovalDecisionError(
          "That action does not exist for this tenant.",
          404,
        );
      }
      const e = existing[0];
      if (e.kind === "flag") {
        throw new ApprovalDecisionError(
          "That is a finding, not a proposal. Findings are never applied.",
          409,
        );
      }
      if (e.status !== "pending") {
        throw new ApprovalDecisionError(`Already ${e.status}.`, 409);
      }
      if (e.expired) {
        throw new ApprovalDecisionError(
          "Expired. It was computed from older data and must be re-proposed.",
          409,
        );
      }
      throw new ApprovalDecisionError("Could not be decided.", 409);
    }
    const a = rows[0];
    await query(
      c,
      "insert into audit_log (tenant_id, actor_user_id, action, entity, before, after) values ($1,$2,$3,$4,$5::jsonb,$6::jsonb)",
      [
        input.tenantId,
        input.userId,
        `action.${input.decision}`,
        `${a.entity_type}:${a.entity_id}`,
        JSON.stringify({ status: "pending", value: a.before_value }),
        JSON.stringify({
          status: input.decision,
          decision: input.decision,
          decided_at: a.decided_at,
          action_type: a.action_type,
          value: a.after_value,
        }),
      ],
    );
  });
}
