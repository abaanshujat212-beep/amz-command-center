import { archiveDashboard,DashboardInputError,updateDashboard } from "@/lib/dashboard-studio"
import { query,withTenantActor } from "@/lib/db"
import { currentContext } from "@/lib/session"
type Context={params:Promise<{id:string}>}
function failure(error:unknown){if(error instanceof DashboardInputError)return Response.json({error:error.message},{status:error.status});throw error}
export async function GET(_request:Request,{params}:Context){const a=await currentContext(),{id}=await params;const rows=await withTenantActor(a.tenantId,a.userId,a.role,c=>query(c,`select d.*,v.definition from dashboard d join dashboard_version v on v.tenant_id=d.tenant_id and v.dashboard_id=d.id and v.version=d.current_version where d.id=$1 and not d.is_archived`,[id]));return rows[0]?Response.json({dashboard:rows[0]}):Response.json({error:"dashboard not found"},{status:404})}
export async function PATCH(request:Request,{params}:Context){try{const a=await currentContext(),{id}=await params,body=await request.json() as Record<string,unknown>;return Response.json({dashboard:await withTenantActor(a.tenantId,a.userId,a.role,c=>updateDashboard(c,a.tenantId,a.userId,a.role,id,body))})}catch(error){return failure(error)}}
export async function DELETE(_request:Request,{params}:Context){try{const a=await currentContext(),{id}=await params;return Response.json(await withTenantActor(a.tenantId,a.userId,a.role,c=>archiveDashboard(c,a.tenantId,a.userId,a.role,id)))}catch(error){return failure(error)}}
