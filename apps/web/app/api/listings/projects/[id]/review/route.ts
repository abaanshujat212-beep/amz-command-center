import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { ListingInputError, reviewListingDraft } from "@/lib/listings"
import { currentContext } from "@/lib/session"

export async function POST(request:Request,context:{params:Promise<{id:string}>}) { try { const actor=await currentContext(); const {id}=await context.params; const body=await request.json().catch(()=>({})); await withTenant(actor.tenantId,c=>reviewListingDraft(c,actor.tenantId,actor.userId,actor.role,id,body)); return NextResponse.json({ok:true}) } catch(error) { if(error instanceof ListingInputError)return NextResponse.json({error:error.message},{status:error.status}); throw error } }
