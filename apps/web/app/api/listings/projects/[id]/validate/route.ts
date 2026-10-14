import { NextResponse } from "next/server"
import { withTenant } from "@/lib/db"
import { ListingInputError, validateLatestListingDraft } from "@/lib/listings"
import { currentContext } from "@/lib/session"

export async function POST(_request:Request,context:{params:Promise<{id:string}>}) {
	try {
		const actor=await currentContext(); const {id}=await context.params
		const validation=await withTenant(actor.tenantId,c=>validateLatestListingDraft(c,actor.tenantId,actor.userId,actor.role,id))
		return NextResponse.json({validation},{status:201})
	} catch(error) {
		if(error instanceof ListingInputError)return NextResponse.json({error:error.message},{status:error.status})
		throw error
	}
}
