import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { listRecommendations,parseRecommendationFilters,RecommendationQueryError } from "@/lib/recommendations"
import { currentContext } from "@/lib/session"

export const dynamic="force-dynamic"
export async function GET(request:Request){try{const actor=await currentContext();const filters=parseRecommendationFilters(new URL(request.url).searchParams);const recommendations=await withTenant(actor.tenantId,c=>listRecommendations(c,actor.tenantId,filters));return NextResponse.json({recommendations,pagination:{limit:filters.limit,offset:filters.offset,count:recommendations.length}})}catch(error){if(error instanceof RecommendationQueryError)return NextResponse.json({error:error.message},{status:error.status});throw error}}
