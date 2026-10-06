import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { createListingProject, listListingProjects, ListingInputError } from "@/lib/listings"
import { currentContext } from "@/lib/session"

export async function GET() { const actor=await currentContext(); return NextResponse.json({projects:await withTenant(actor.tenantId,c=>listListingProjects(c,actor.tenantId))}) }
export async function POST(request:Request) { try { const actor=await currentContext(); const body=await request.json().catch(()=>({})); const project=await withTenant(actor.tenantId,c=>createListingProject(c,actor.tenantId,actor.userId,actor.role,body)); return NextResponse.json({project},{status:201}) } catch(error) { if(error instanceof ListingInputError)return NextResponse.json({error:error.message},{status:error.status}); throw error } }
