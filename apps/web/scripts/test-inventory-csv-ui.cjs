const fs=require('node:fs'),assert=require('node:assert/strict'),Module=require('node:module'),path=require('node:path')
const root=path.resolve(__dirname,'..'),requireWeb=Module.createRequire(root+'/package.json'),ts=requireWeb('typescript'),React=requireWeb('react'),{renderToStaticMarkup}=requireWeb('react-dom/server')
const filename=path.join(root,'components/inventory-csv-import.tsx'),m=new Module(filename)
m.filename=filename;m.paths=Module._nodeModulePaths(root)
const native=m.require.bind(m)
m.require=name=>name==='next/navigation'?{useRouter:()=>({refresh(){}})}:native(name)
m._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,filename)
const {INVENTORY_CSV_TEMPLATE,MAX_INVENTORY_CSV_BYTES,inventoryCsvText,inventoryCsvPreview,inventoryCsvCommitCounts,InventoryCsvImport}=m.exports
const csv='locationCode,sku,sourceReference,observedAt,availableQty\r\nWH-1,SKU-é,count-é-1,2026-01-01T12:00:00Z,0\r\n'
assert.equal(inventoryCsvText(csv),csv)
assert.throws(()=>inventoryCsvText('   '),/Choose a CSV/)
assert.equal(inventoryCsvText('a'.repeat(MAX_INVENTORY_CSV_BYTES)).length,MAX_INVENTORY_CSV_BYTES)
assert.throws(()=>inventoryCsvText('é'.repeat(MAX_INVENTORY_CSV_BYTES/2+1)),/128 KiB/)
assert.equal(INVENTORY_CSV_TEMPLATE.trim().split('\n').length,1)
assert.match(INVENTORY_CSV_TEMPLATE,/(?:^|,)sourceReference,/)
assert.match(INVENTORY_CSV_TEMPLATE,/(?:^|,)observedAt,/)
const values={locationCode:'WH-1',sku:'SKU-é',sourceReference:'count-é-1',observedAt:'2026-01-01T12:00:00.000Z',availableQty:0,onHandQty:null,inboundQty:5}
const good={mode:'preview',valid:true,totalRows:1,validRows:1,errorRows:0,rows:[{rowNumber:2,valid:true,errors:[],values}]}
const preview=inventoryCsvPreview(good)
assert.equal(preview.valid,true)
assert.deepEqual(preview.rows[0].values,values)
assert.equal(preview.rows[0].values.availableQty,0)
assert.equal(preview.rows[0].values.onHandQty,null)
for(const changed of [{mode:'commit'},{valid:false},{totalRows:101},{totalRows:2},{validRows:0},{errorRows:1},{rows:[{rowNumber:2,valid:true,errors:['failure'],values}]},{rows:[{rowNumber:2,valid:true,errors:[],values:null}]},{rows:[{rowNumber:2,valid:false,errors:[],values:null}]},{rows:[{rowNumber:1,valid:true,errors:[],values}]}]) assert.throws(()=>inventoryCsvPreview({...good,...changed}))
const bad={mode:'preview',valid:false,totalRows:1,validRows:0,errorRows:1,rows:[{rowNumber:3,valid:false,errors:['sourceReference is required'],values:null}]}
assert.equal(inventoryCsvPreview(bad).valid,false)
assert.equal(inventoryCsvPreview({...bad,mode:'commit'},'commit').errorRows,1)
assert.deepEqual(inventoryCsvCommitCounts({mode:'commit',totalRows:2,inserted:1,unchanged:1},2),{totalRows:2,inserted:1,unchanged:1})
for(const value of [{mode:'preview',totalRows:2,inserted:1,unchanged:1},{mode:'commit',totalRows:2,inserted:2,unchanged:1},{mode:'commit',totalRows:1,inserted:1,unchanged:0},{mode:'commit',totalRows:2,inserted:-1,unchanged:3}]) assert.throws(()=>inventoryCsvCommitCounts(value,2))
const html=renderToStaticMarkup(React.createElement(InventoryCsvImport))
assert.match(html,/Import stock counts from CSV/)
assert.match(html,/Download CSV headers/)
assert.match(html,/Required columns: locationCode, sku, sourceReference, observedAt/)
assert.match(html,/type="file"/)
assert.match(html,/name="csv"/)
assert.doesNotMatch(html,/Confirm import|type="checkbox"|name="tenantId"|name="sourceType"/)
async function roles() {
 const pageFile=path.join(root,'app/inventory/page.tsx'),pageModule=new Module(pageFile);pageModule.filename=pageFile;pageModule.paths=Module._nodeModulePaths(root)
 function plain(relative){const file=path.join(root,relative),mod=new Module(file);mod._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,file);return mod.exports}
 const filters=plain('lib/inventory-workspace.ts'),rbac=plain('lib/rbac.ts');let role='owner',reads=0,authenticated=true
 const pageNative=pageModule.require.bind(pageModule)
 pageModule.require=name=>{
  if(name==='next/link')return {default:({children,href})=>React.createElement('a',{href},children)}
  if(name==='@/components/inventory-csv-import')return {InventoryCsvImport}
  if(name==='@/components/manual-inventory-form')return {ManualInventoryForm:()=>null}
  if(name==='@/components/inventory-workspace')return {InventoryWorkspace:()=>null}
  if(name==='@/lib/inventory-workspace')return filters
  if(name==='@/lib/rbac')return rbac
  if(name==='@/lib/session')return {currentContext:async()=>{if(!authenticated)throw new Error('Sign in required');return {tenantId:'tenant-1',role}}}
  if(name==='@/lib/db')return {withTenant:async(tenant,callback)=>{assert.equal(tenant,'tenant-1');reads++;return callback({})}}
  if(name==='@/lib/inventory')return {inventorySnapshotRead:async()=>({snapshots:[]}),inventoryForecastRead:async()=>[]}
  return pageNative(name)
 }
 pageModule._compile(ts.transpileModule(fs.readFileSync(pageFile,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,pageFile)
 for(const value of ['owner','admin','user','analyst','viewer']){role=value;const markup=renderToStaticMarkup(await pageModule.exports.default({searchParams:Promise.resolve({})}));if(['owner','admin'].includes(role))assert.match(markup,/Import stock counts from CSV/);else assert.doesNotMatch(markup,/Import stock counts from CSV/)}
 authenticated=false;const before=reads;await assert.rejects(()=>pageModule.exports.default({searchParams:Promise.resolve({})}),/Sign in required/);assert.equal(reads,before)
 console.log('CSV UI checks passed: exact source CSV, byte limit, header-only template, preview/commit validation, null/zero, role gating and initial accessible render.')
}
roles().catch(error=>{console.error(error);process.exitCode=1})
