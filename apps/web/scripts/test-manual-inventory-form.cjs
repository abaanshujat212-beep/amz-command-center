const fs = require('node:fs')
const assert = require('node:assert/strict')
const Module = require('node:module')
const path = require('node:path')
const root = path.resolve(__dirname, '..')
const requireWeb = Module.createRequire(root + '/package.json')
const ts = requireWeb('typescript')
const React = requireWeb('react')
const { renderToStaticMarkup } = requireWeb('react-dom/server')
const typesFile = path.join(root, 'lib/inventory-location-types.ts')
const typesModule = new Module(typesFile)
typesModule._compile(ts.transpileModule(fs.readFileSync(typesFile,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,typesFile)
const filename = path.join(root, 'components/manual-inventory-form.tsx')
const m = new Module(filename)
m.filename = filename
m.paths = Module._nodeModulePaths(root)
const native = m.require.bind(m)
m.require = name => name === '@/lib/inventory-location-types' ? typesModule.exports : name === 'next/navigation' ? {useRouter: () => ({refresh() {}})} : name === 'next/link' ? {default: ({children, href, ...props}) => React.createElement('a', {href, ...props}, children)} : native(name)
m._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,filename)
const {manualInventoryPayload,ManualInventoryForm} = m.exports
const locations = [{locationCode:'WH-1',locationName:'Existing warehouse'}]
function fields(overrides={}) {
 const data=new FormData()
 for(const [key,value] of Object.entries({locationCode:' WH-1 ',locationName:'Do not overwrite',sku:' SKU&1 ',sourceReference:' count-1 ',observedAt:'2026-01-01T12:00',freshness:'current',availableQty:'0',onHandQty:'',inboundQty:'125.5',inTransitQty:'.5',...overrides})) data.set(key,value)
 return data
}
const now=Date.parse('2026-01-02T00:00:00Z')
const payload=manualInventoryPayload(fields(),locations,now)
assert.equal(payload.availableQty,0)
assert.equal(payload.onHandQty,null)
assert.equal(payload.reservedQty,null)
assert.equal(payload.inboundQty,125.5)
assert.equal(payload.inTransitQty,0.5)
assert.equal(payload.locationName,undefined)
assert.equal(payload.observedAt,'2026-01-01T12:00:00.000Z')
assert.equal(payload.expectedAvailableAt,null)
assert.equal(payload.sku,'SKU&1')
assert.equal(payload.sourceReference,'count-1')
assert.equal(payload.tenantId,undefined)
assert.equal(payload.sourceType,undefined)
assert.deepEqual(manualInventoryPayload(fields(),locations,now),payload)
assert.equal(manualInventoryPayload(fields({locationCode:'NEW',locationName:' New warehouse '}),locations,now).locationName,'New warehouse')
assert.equal(manualInventoryPayload(fields({locationCode:'NOT-IN-PAGE',locationName:''}),locations,now).locationName,undefined)
assert.equal(manualInventoryPayload(fields({expectedAvailableAt:'2027-01-01T09:30'}),locations,now).expectedAvailableAt,'2027-01-01T09:30:00.000Z')
for(const value of ['-1','NaN','Infinity','1e3','0.00001','1000000000000','hello']) assert.throws(()=>manualInventoryPayload(fields({availableQty:value}),locations,now),/Available now/)
for(const observedAt of ['2026-01-03T00:00','2026-02-30T12:00','2026-01-01','invalid']) assert.throws(()=>manualInventoryPayload(fields({observedAt}),locations,now),/Observation time/)
assert.throws(()=>manualInventoryPayload(fields({sourceReference:''}),locations,now),/count reference/)
assert.throws(()=>manualInventoryPayload(fields({sku:''}),locations,now),/SKU/)
assert.throws(()=>manualInventoryPayload(fields({freshness:'fake'}),locations,now),/count quality/)
const html=renderToStaticMarkup(React.createElement(ManualInventoryForm,{locations,initialObservedAt:'2026-01-01T12:00:00Z'}))
assert.match(html,/Record a stock count/)
assert.match(html,/Observed at \(UTC\)/)
assert.match(html,/New location name/)
assert.match(html,/value="WH-1"/)
assert.match(html,/value="2026-01-01T12:00"/)
assert.match(html,/placeholder="Unknown"/)
assert.match(html,/name="availableQty"/)
assert.match(html,/name="inboundQty"/)
assert.match(html,/name="inTransitQty"/)
assert.doesNotMatch(html,/name="tenantId"|name="sourceType"/)
console.log('Manual inventory form: nullable quantities, zero, retry identity, new/existing location payloads, timestamps, validation and accessible initial render passed.')

async function checkPageRoles() {
 const pageFile=path.join(root,'app/inventory/page.tsx')
 let role='owner',tenantCalls=0,authenticated=true
 const filtersFile=path.join(root,'lib/inventory-workspace.ts')
 const filtersModule=new Module(filtersFile)
 filtersModule._compile(ts.transpileModule(fs.readFileSync(filtersFile,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,filtersFile)
 const rbacFile=path.join(root,'lib/rbac.ts')
 const rbacModule=new Module(rbacFile)
 rbacModule._compile(ts.transpileModule(fs.readFileSync(rbacFile,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,rbacFile)
 const pageModule=new Module(pageFile)
 pageModule.filename=pageFile
 pageModule.paths=Module._nodeModulePaths(root)
 const pageNative=pageModule.require.bind(pageModule)
 pageModule.require=name=>{
  if(name==='next/link') return {default:({children,href,...props})=>React.createElement('a',{href,...props},children)}
  if(name==='@/components/inventory-csv-import') return {InventoryCsvImport:()=>null}
  if(name==='@/components/manual-inventory-form') return {ManualInventoryForm}
  if(name==='@/components/inventory-workspace') return {InventoryWorkspace:()=>React.createElement('div',null,'Inventory workspace')}
  if(name==='@/lib/inventory-workspace') return filtersModule.exports
  if(name==='@/lib/rbac') return rbacModule.exports
  if(name==='@/lib/session') return {currentContext:async()=>{if(!authenticated)throw new Error('Sign in required');return {tenantId:'tenant-1',role}}}
  if(name==='@/lib/db') return {withTenant:async(tenant,callback)=>{assert.equal(tenant,'tenant-1');tenantCalls++;return callback({})}}
  if(name==='@/lib/inventory') return {inventorySnapshotRead:async()=>({snapshots:[{sku:'SKU-1',locationCode:'WH-1',locationName:'Main warehouse'}]}),inventoryForecastRead:async()=>[]}
  return pageNative(name)
 }
 pageModule._compile(ts.transpileModule(fs.readFileSync(pageFile,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,pageFile)
 for(const value of ['owner','admin','user','analyst','viewer']) {
  role=value
  const tree=await pageModule.exports.default({searchParams:Promise.resolve({})})
  const markup=renderToStaticMarkup(tree)
  if(['owner','admin'].includes(role)) assert.match(markup,/Record a stock count/)
  else {assert.doesNotMatch(markup,/Record a stock count/);assert.match(markup,/read-only inventory access/)}
 }
 authenticated=false
 const previousCalls=tenantCalls
 await assert.rejects(()=>pageModule.exports.default({searchParams:Promise.resolve({})}),/Sign in required/)
 assert.equal(tenantCalls,previousCalls)
 console.log('Inventory page role checks passed: owner/admin form, other roles read-only, unauthenticated reads blocked.')
}
checkPageRoles().catch(error=>{console.error(error);process.exitCode=1})

assert.equal(manualInventoryPayload(fields({locationCode:'NEW',locationName:'New location'}),locations,now).locationType,'own_warehouse')
for(const option of typesModule.exports.MANUAL_INVENTORY_LOCATION_TYPES) {
 assert.equal(manualInventoryPayload(fields({locationCode:'NEW',locationName:'New location',locationType:option.value}),locations,now).locationType,option.value)
 assert.match(html,new RegExp('value="'+option.value+'"'))
}
assert.equal(manualInventoryPayload(fields({locationType:'supplier'}),locations,now).locationType,undefined)
assert.equal(manualInventoryPayload(fields({locationCode:'NOT-IN-PAGE',locationName:'',locationType:'supplier'}),locations,now).locationType,undefined)
for(const locationType of ['amazon_fba','amazon_awd','invalid']) assert.throws(()=>manualInventoryPayload(fields({locationCode:'NEW',locationName:'New location',locationType}),locations,now),/location type/)
assert.match(html,/New location type/)
assert.doesNotMatch(html,/value="amazon_fba"|value="amazon_awd"/)
console.log('Manual form local types: whitelist, default, creation-only payload, existing/filtered-location omission and Amazon exclusion passed.')
