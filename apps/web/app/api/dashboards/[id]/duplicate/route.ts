import { DashboardInputError,duplicateDashboard } from "@/lib/dashboard-studio"
import { withTenantActor } from "@/lib/db"
import { currentContext } from "@/lib/session"
export async function POST(request:Request,{params}:{params:Promise<{id:string}>}){try{const a=await currentContext(),{id}=await params,body=await request.json().catch(()=>({})) as Record<string,unknown>;const dashboard=await withTenantActor(a.tenantId,a.userId,a.role,c=>duplicateDashboard(c,a.tenantId,a.userId,a.role,id,body));return Response.json({dashboard},{status:201})}catch(error){if(error instanceof DashboardInputError)return Response.json({error:error.message},{status:error.status});throw error}}
