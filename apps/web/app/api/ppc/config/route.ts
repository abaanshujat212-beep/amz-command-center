import { withTenant } from "@/lib/db"
import { listConfiguration,mayWrite } from "@/lib/ppc-configuration"
import { currentContext } from "@/lib/session"
export async function GET(){const a=await currentContext();return Response.json(await withTenant(a.tenantId,async c=>({...await listConfiguration(c,a.tenantId),canWrite:await mayWrite(c,a.tenantId,a.userId,a.role),actor:{id:a.userId,role:a.role}})))}
