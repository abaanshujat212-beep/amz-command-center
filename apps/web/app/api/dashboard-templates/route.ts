import { listDashboardTemplates } from "@/lib/dashboard-studio"
import { withTenantActor } from "@/lib/db"
import { currentContext } from "@/lib/session"
export async function GET(){const a=await currentContext();return Response.json({templates:await withTenantActor(a.tenantId,a.userId,a.role,listDashboardTemplates)})}
