import assert from "node:assert/strict"
import {readFileSync} from "node:fs"
import {stripTypeScriptTypes} from "node:module"
import test from "node:test"

const source=readFileSync(new URL("../lib/settings-api-contract.ts",import.meta.url),"utf8")
const contractUrl=`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(source)).toString("base64")}`
const mod=await import(contractUrl)
test("company settings are strictly bounded and reject safety switches",()=>{
  assert.deepEqual(mod.validateCompanySettings({name:" My company ",timezone:"Europe/London"}),{name:"My company",timezone:"Europe/London"})
  for(const raw of [null,[],{name:"x",timezone:"UTC"},{name:"Client",timezone:"invalid"},
    {name:"Client",timezone:"UTC",automation_enabled:true},{name:"Client",timezone:"UTC",dry_run:false},
    {name:"Client",timezone:"UTC",ads_profile_id:"123"}]) assert.throws(()=>mod.validateCompanySettings(raw))
})
test("revision changes for each editable field and is stable for the same values",()=>{
  const base={name:"Client",timezone:"Europe/London"}
  assert.equal(mod.settingsRevision(base),mod.settingsRevision({...base}))
  assert.notEqual(mod.settingsRevision(base),mod.settingsRevision({...base,name:"Other"}))
  assert.notEqual(mod.settingsRevision(base),mod.settingsRevision({...base,timezone:"UTC"}))
})

test("settings endpoint requires credentials, scope, revision and audits permitted changes",async()=>{
  const tenant="12345678-1234-1234-1234-123456789abc"
  const statements=[]
  let authorized=true
  const dbUrl=`data:text/javascript;base64,${Buffer.from(`export const query=(...args)=>globalThis.settingsApiTest.query(...args); export const withTenant=(...args)=>globalThis.settingsApiTest.withTenant(...args);`).toString("base64")}`
  globalThis.settingsApiTest={
    withTenant:async(id,fn)=>{assert.equal(id,tenant);return fn({})},
    query:async(c,sql,values)=>{
      statements.push({sql,values})
      if(sql.includes("select k.id")) return authorized?[{id:"key",created_by:"actor"}]:[]
      if(sql.includes("select t.name")) return [{name:"Client",timezone:"UTC"}]
      return []
    }
  }
  const service=readFileSync(new URL("../lib/settings-api.ts",import.meta.url),"utf8")
    .replace('"@/lib/db"',JSON.stringify(dbUrl)).replace('"@/lib/settings-api-contract"',JSON.stringify(contractUrl))
  const {companySettingsRequest}=await import(`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(service)).toString("base64")}`)
  const headers={"x-tenant-id":tenant,authorization:`Bearer ak_live_${"a".repeat(32)}`}
  const request=(extra={},body)=>new Request("http://localhost/api/settings/company",{method:body?"PATCH":"GET",headers:{...headers,...extra},body:body&&JSON.stringify(body)})
  try {
    await assert.rejects(()=>companySettingsRequest(new Request("http://localhost"),false),e=>e.status===401)
    authorized=false
    await assert.rejects(()=>companySettingsRequest(request(),false),e=>e.status===403)
    authorized=true
    const current=await companySettingsRequest(request(),false)
    assert.deepEqual(current.settings,{name:"Client",timezone:"UTC"})
    statements.length=0
    await assert.rejects(()=>companySettingsRequest(request({}, {name:"Changed",timezone:"UTC"}),true),e=>e.status===412)
    assert.equal(statements.filter(s=>s.sql.startsWith("update")).length,0)
    statements.length=0
    const changed=await companySettingsRequest(request({"if-match":current.revision},{name:"Changed",timezone:"Europe/London"}),true)
    assert.equal(changed.settings.name,"Changed")
    assert.equal(statements[0].values[2],"settings:write")
    assert.equal(statements.filter(s=>s.sql.includes("insert into audit_log")).length,1)
    assert.equal(statements.filter(s=>s.sql.startsWith("update tenant set name")).length,1)
    await assert.rejects(()=>companySettingsRequest(request({}, {name:"Changed",timezone:"UTC",dry_run:false}),true),e=>e.status===400)
  } finally {delete globalThis.settingsApiTest}
})
