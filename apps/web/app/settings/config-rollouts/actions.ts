"use server"
import { revalidatePath } from "next/cache"
import { createSimulation,parseProposed,RolloutInputError,transitionRollout } from "@/lib/config-rollouts"
import { query,withTenant } from "@/lib/db"
import { currentContext } from "@/lib/session"
const text=(f:FormData,k:string)=>String(f.get(k)??"").trim()
function admin(role:string){if(role!=="owner"&&role!=="admin")throw new RolloutInputError("Owner or admin required.")}
export async function preview(form:FormData){const a=await currentContext();admin(a.role);await withTenant(a.tenantId,c=>createSimulation(c,a.tenantId,a.userId,parseProposed(text(form,"proposed")),Number(text(form,"exposureLimit"))));revalidatePath("/settings/config-rollouts")}
export async function transition(form:FormData){const a=await currentContext();admin(a.role);const id=text(form,"id"),state=text(form,"state"),reason=text(form,"reason"),pct=Number(text(form,"pct"));await withTenant(a.tenantId,async c=>{const result=await transitionRollout(c,a.tenantId,a.userId,id,state,pct,reason);await query(c,`insert into audit_log(tenant_id,actor_user_id,action,entity,after) values($1,$2,$3,$4,$5::jsonb)`,[a.tenantId,a.userId,`configuration_rollout.${result.state.toLowerCase()}`,`simulation:${id}`,JSON.stringify({...result,reason})])});revalidatePath("/settings/config-rollouts")}
