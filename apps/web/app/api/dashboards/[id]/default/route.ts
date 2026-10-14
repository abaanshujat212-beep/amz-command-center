import { clearDefaultDashboard,DashboardInputError,setDefaultDashboard } from "@/lib/dashboard-studio"
import { withTenantActor } from "@/lib/db"
import { currentContext } from "@/lib/session"
type Context={params:Promise<{id:string}>}
export async function PUT(_request:Request,{params}:Context){try{const a=await currentContext(),{id}=await params;return Response.json(await withTenantActor(a.tenantId,a.userId,a.role,c=>setDefaultDashboard(c,a.tenantId,a.userId,id)))}catch(error){if(error instanceof DashboardInputError)return Response.json({error:error.message},{status:error.status});throw error}}
export async function DELETE(_request:Request,{params}:Context){const a=await currentContext(),{id}=await params;return Response.json(await withTenantActor(a.tenantId,a.userId,a.role,c=>clearDefaultDashboard(c,a.tenantId,a.userId,id)))}
