import { strict as assert } from "node:assert"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import { runInNewContext } from "node:vm"
import { stripTypeScriptTypes } from "node:module"
import { parseListingVersion } from "../lib/listing-preview-input.ts"

const source = readFileSync(new URL("../lib/listings.ts",import.meta.url),"utf8")
const compiled = stripTypeScriptTypes(source
	.replace(/^import [^\n]+\n/gm,"")
	.replace(/^export /gm,""),{mode:"transform"}) + "\nmodule.exports={getListingProjectPreview}"
const id="ea9b57c0-c0ff-43d0-b095-2bd572c0a8aa"

function preview(rows) {
	const calls=[]
	const mod={exports:{}}
	runInNewContext(compiled,{module:mod,query:async(_client,sql,args)=>{
		assert.match(sql,/^select /)
		assert.match(sql,/tenant_id\s*=\s*\$1/)
		calls.push({sql,args:Array.from(args)})
		assert.ok(rows.length>0,"unexpected query")
		return rows.shift()
	}})
	return {calls, query:(projectId,version)=>mod.exports.getListingProjectPreview({},"tenant",projectId,version)}
}

test("only accepts explicit bounded PostgreSQL integer versions",()=>{
	for (const value of [undefined,["1"],"0","01","2e3","-1","2147483648","9007199254740993"," 1 ","1.2"]) assert.equal(parseListingVersion(value),null)
	assert.equal(parseListingVersion("1"),1)
	assert.equal(parseListingVersion("2147483647"),2147483647)
})
test("missing or foreign project prevents dependent queries; invalid IDs never query",async()=>{
	const p=preview([[]])
	assert.equal(await p.query("invalid",null),null)
	assert.equal(p.calls.length,0)
	assert.equal(await p.query(id,null),null)
	assert.deepEqual(p.calls.map(c=>c.args),[["tenant",id]])
})
test("historic draft ties its validation and issues to the authorized project; reads only",async()=>{
	const p=preview([[{id}], [{version:3},{version:2}], [{id:"draft-two",version:2}], [{id:"run-two",passed:false}],
		[{code:"blocked"}], [{version:2,decision:"changes_requested"}]])
	const result=await p.query(id,2)
	assert.equal(result.draft.version,2)
	assert.equal(result.validation.passed,false)
	assert.equal(result.issues[0].code,"blocked")
	assert.equal(result.reviews[0].decision,"changes_requested")
	assert.deepEqual(p.calls.map(c=>c.args),[["tenant",id],["tenant",id],["tenant",id,2],
		["tenant",id,"draft-two"],["tenant","run-two"],["tenant",id]])
	assert.match(p.calls[5].sql,/d\.project_id=e\.project_id/)
})
test("no validation work occurs for a draft that lacks a recorded run",async()=>{
	const p=preview([[{id}], [], [], []])
	const data=await p.query(id,null)
	assert.equal(p.calls.length,4)
	assert.equal(data.draft,null)
	assert.equal(data.validation,null)
	assert.equal(data.issues.length,0)
})
