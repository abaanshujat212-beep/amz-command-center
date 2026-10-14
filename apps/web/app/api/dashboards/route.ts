import { DashboardInputError,createDashboard,listDashboards } from "@/lib/dashboard-studio"
import { withTenantActor } from "@/lib/db"
import { currentContext } from "@/lib/session"

function failure(error:unknown){if(error instanceof DashboardInputError)return Response.json({error:error.message},{status:error.status});throw error}
export async function GET(){const a=await currentContext();return Response.json({dashboards:await withTenantActor(a.tenantId,a.userId,a.role,c=>listDashboards(c,a.userId))})}
export async function POST(request:Request){try{const a=await currentContext(),body=await request.json() as Record<string,unknown>;const dashboard=await withTenantActor(a.tenantId,a.userId,a.role,c=>createDashboard(c,a.tenantId,a.userId,a.role,body));return Response.json({dashboard},{status:201})}catch(error){return failure(error)}}
