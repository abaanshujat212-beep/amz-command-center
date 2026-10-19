import { currentContext } from "@/lib/session"
import { withTenant } from "@/lib/db"
import { createFormula, latestScores, ScoreInputError } from "@/lib/ppc-scores"

export async function GET(request:Request){const actor=await currentContext(),url=new URL(request.url),scopeType=url.searchParams.get("scopeType")??"account",scopeId=url.searchParams.get("scopeId")??actor.tenantId;if(!["account","portfolio","campaign"].includes(scopeType))return Response.json({error:"invalid scopeType"},{status:400});return Response.json({scores:await withTenant(actor.tenantId,c=>latestScores(c,actor.tenantId,scopeType,scopeId))})}
export async function POST(request:Request){const actor=await currentContext();try{const body=await request.json() as Record<string,unknown>;const result=await withTenant(actor.tenantId,c=>createFormula(c,actor.tenantId,actor.userId,actor.role,body));return Response.json(result,{status:201})}catch(error){if(error instanceof ScoreInputError)return Response.json({error:error.message},{status:error.status});throw error}}
