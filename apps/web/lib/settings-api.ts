import { createHash } from "node:crypto"
import { query, withTenant } from "@/lib/db"
import { SettingsApiError, settingsRevision, validateCompanySettings, type CompanySettings } from "@/lib/settings-api-contract"

export const SETTINGS_KEY_SQL = `select k.id,k.created_by from tenant_api_key k
  join tenant_member m on m.tenant_id=k.tenant_id and m.user_id=k.created_by
  join tenant t on t.id=k.tenant_id
  where k.tenant_id=$1 and k.key_hash=$2 and k.revoked_at is null
    and $3=any(k.scopes) and m.role in ('owner','admin') and t.status='active'
  for update of k,m,t`
export const COMPANY_SETTINGS_SQL = `select t.name,s.timezone from tenant t
  join tenant_settings s on s.tenant_id=t.id where t.id=$1 for update of t,s`

export async function companySettingsRequest(request:Request, update:boolean) {
  const tenant=request.headers.get("x-tenant-id")??""
  const auth=request.headers.get("authorization")??""
  if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(tenant)||!/^Bearer ak_live_[A-Za-z0-9_-]{32}$/.test(auth)) throw new SettingsApiError("Invalid account credentials",401)
  let proposed:CompanySettings|undefined
  if(update) {
    const text=await request.text()
    if(text.length>2048) throw new SettingsApiError("Settings payload too large",413)
    let raw:unknown
    try {raw=JSON.parse(text)} catch {throw new SettingsApiError("Invalid JSON",400)}
    proposed=validateCompanySettings(raw)
  }
  const hash=createHash("sha256").update(auth.slice(7)).digest("hex")
  return withTenant(tenant,async c=>{
    const [key]=await query<{id:string;created_by:string}>(c,SETTINGS_KEY_SQL,[tenant,hash,update?"settings:write":"settings:read"])
    if(!key) throw new SettingsApiError("Invalid account credentials or scope",403)
    const [before]=await query<CompanySettings>(c,COMPANY_SETTINGS_SQL,[tenant])
    if(!before) throw new SettingsApiError("Company settings unavailable",404)
    if(update&&request.headers.get("if-match")!==settingsRevision(before)) throw new SettingsApiError("Settings changed; read current settings before editing",412)
    const after=proposed??before
    if(proposed&&settingsRevision(before)!==settingsRevision(proposed)) {
      await query(c,"update tenant set name=$2 where id=$1",[tenant,proposed.name])
      await query(c,"update tenant_settings set timezone=$2 where tenant_id=$1",[tenant,proposed.timezone])
      await query(c,`insert into audit_log(tenant_id,actor_user_id,action,entity,before,after)
        values($1,$2,'tenant.company_settings_api_updated',$3,$4::jsonb,$5::jsonb)`,
        [tenant,key.created_by,`tenant:${tenant}`,JSON.stringify(before),JSON.stringify({...after,api_key_id:key.id})])
    }
    await query(c,"update tenant_api_key set last_used_at=now() where tenant_id=$1 and id=$2",[tenant,key.id])
    return {settings:after,revision:settingsRevision(after)}
  })
}
