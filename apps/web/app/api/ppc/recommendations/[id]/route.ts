import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { recommendationDetail,RecommendationQueryError } from "@/lib/recommendations"
import { currentContext } from "@/lib/session"

export const dynamic="force-dynamic"
export async function GET(_request:Request,context:{params:Promise<{id:string}>}){try{const actor=await currentContext();const{id}=await context.params;const recommendation=await withTenant(actor.tenantId,c=>recommendationDetail(c,actor.tenantId,id));return NextResponse.json({recommendation})}catch(error){if(error instanceof RecommendationQueryError)return NextResponse.json({error:error.message},{status:error.status});throw error}}
