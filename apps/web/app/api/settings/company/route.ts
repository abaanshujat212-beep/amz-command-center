import { NextResponse } from "next/server"
import { companySettingsRequest } from "@/lib/settings-api"
import { SettingsApiError } from "@/lib/settings-api-contract"

export const dynamic="force-dynamic"
async function handle(request:Request,update:boolean) {
  try {
    const result=await companySettingsRequest(request,update)
    return NextResponse.json(result,{headers:{"Cache-Control":"no-store",ETag:result.revision}})
  } catch(error) {
    if(error instanceof SettingsApiError) return NextResponse.json({error:error.message},{status:error.status,headers:{"Cache-Control":"no-store"}})
    return NextResponse.json({error:"Company settings service unavailable"},{status:503,headers:{"Cache-Control":"no-store"}})
  }
}
export const GET=(request:Request)=>handle(request,false)
export const PATCH=(request:Request)=>handle(request,true)
