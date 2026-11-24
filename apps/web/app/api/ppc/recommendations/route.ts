import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { listRecommendations,parseRecommendationFilters,RecommendationQueryError } from "@/lib/recommendations"
import { recommendationPage } from "@/lib/recommendation-filters"
import { currentContext } from "@/lib/session"

export const dynamic="force-dynamic"
export async function GET(request:Request){try{const actor=await currentContext();const filters=parseRecommendationFilters(new URL(request.url).searchParams);const recommendations=await withTenant(actor.tenantId,c=>listRecommendations(c,actor.tenantId,filters,true));return NextResponse.json(recommendationPage(recommendations,filters))}catch(error){if(error instanceof RecommendationQueryError)return NextResponse.json({error:error.message},{status:error.status});throw error}}
