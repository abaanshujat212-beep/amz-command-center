import { DashboardInputError,upgradeDashboardTemplate } from "@/lib/dashboard-studio"
import { withTenantActor } from "@/lib/db"
import { currentContext } from "@/lib/session"
export async function PATCH(_request:Request,{params}:{params:Promise<{id:string}>}){try{const a=await currentContext(),{id}=await params;return Response.json({dashboard:await withTenantActor(a.tenantId,a.userId,a.role,c=>upgradeDashboardTemplate(c,a.tenantId,a.userId,a.role,id))})}catch(error){if(error instanceof DashboardInputError)return Response.json({error:error.message},{status:error.status});throw error}}
