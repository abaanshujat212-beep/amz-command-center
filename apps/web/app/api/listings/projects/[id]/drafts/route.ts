import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { createListingDraft, ListingInputError } from "@/lib/listings"
import { currentContext } from "@/lib/session"

export async function POST(request:Request,context:{params:Promise<{id:string}>}) { try { const actor=await currentContext(); const {id}=await context.params; const body=await request.json().catch(()=>({})); const draft=await withTenant(actor.tenantId,c=>createListingDraft(c,actor.tenantId,actor.userId,actor.role,id,body)); return NextResponse.json({draft},{status:201}) } catch(error) { if(error instanceof ListingInputError)return NextResponse.json({error:error.message},{status:error.status}); throw error } }
